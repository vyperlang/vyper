from __future__ import annotations

import contextlib
import copy
from dataclasses import dataclass
from typing import Any, Optional, TypeVar

import cbor2

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.evm.opcodes import get_opcodes, version_check
from vyper.exceptions import CodegenPanic, CompilerPanic
from vyper.ir.optimizer import COMMUTATIVE_OPS
from vyper.utils import MemoryPositions, OrderedSet
from vyper.version import version_tuple

PUSH_OFFSET = 0x5F
DUP_OFFSET = 0x7F
SWAP_OFFSET = 0x8F


def num_to_bytearray(x):
    o = []
    while x > 0:
        o.insert(0, x % 256)
        x //= 256
    return o


def PUSH(x):
    bs = num_to_bytearray(x)
    # starting in shanghai, can do push0 directly with no immediates
    if len(bs) == 0 and not version_check(begin="shanghai"):
        bs = [0]
    return [f"PUSH{len(bs)}"] + bs


# push an exact number of bytes
def PUSH_N(x, n):
    o = []
    for _i in range(n):
        o.insert(0, x % 256)
        x //= 256
    assert x == 0
    return [f"PUSH{len(o)}"] + o


#####################################
# assembly data structures and utils
#####################################


class Label:
    def __init__(self, label: str):
        assert isinstance(label, str)
        self.label = label

    def __repr__(self):
        return f"LABEL {self.label}"

    def __eq__(self, other):
        if not isinstance(other, Label):
            return False
        return self.label == other.label

    def __hash__(self):
        return hash(self.label)


@dataclass
class DataHeader:
    label: Label

    def __repr__(self):
        return f"DATA {self.label.label}"


# this could be fused with Label, the only difference is if
# it gets looked up from const_map or symbol_map.
class CONSTREF:
    def __init__(self, label: str):
        assert isinstance(label, str)
        self.label = label

    def __repr__(self):
        return f"CONSTREF {self.label}"

    def __eq__(self, other):
        if not isinstance(other, CONSTREF):
            return False
        return self.label == other.label

    def __hash__(self):
        return hash(self.label)


class CONST:
    def __init__(self, name: str, value: int):
        assert isinstance(name, str)
        assert isinstance(value, int)
        self.name = name
        self.value = value

    def __repr__(self):
        return f"CONST {self.name} {self.value}"

    def __eq__(self, other):
        if not isinstance(other, CONST):
            return False
        return self.name == other.name and self.value == other.value


class PUSHLABEL:
    def __init__(self, label: Label):
        assert isinstance(label, Label), label
        self.label = label

    def __repr__(self):
        return f"PUSHLABEL {self.label.label}"

    def __eq__(self, other):
        if not isinstance(other, PUSHLABEL):
            return False
        return self.label == other.label

    def __hash__(self):
        return hash(self.label)


# push the result of an addition (which might be resolvable at compile-time)
class PUSH_OFST:
    def __init__(self, label: Label | CONSTREF, ofst: int):
        # label can be Label or CONSTREF
        assert isinstance(label, (Label, CONSTREF))
        self.label = label
        self.ofst = ofst

    def __repr__(self):
        label = self.label
        if isinstance(label, Label):
            label = label.label  # str
        return f"PUSH_OFST({label}, {self.ofst})"

    def __eq__(self, other):
        if not isinstance(other, PUSH_OFST):
            return False
        return self.label == other.label and self.ofst == other.ofst

    def __hash__(self):
        return hash((self.label, self.ofst))


class DATA_ITEM:
    def __init__(self, item: bytes | Label):
        self.data = item

    def __repr__(self):
        if isinstance(self.data, bytes):
            return f"DATABYTES {self.data.hex()}"
        elif isinstance(self.data, Label):
            return f"DATALABEL {self.data.label}"


def JUMP(label: Label):
    return [PUSHLABEL(label), "JUMP"]


def JUMPI(label: Label):
    return [PUSHLABEL(label), "JUMPI"]


def mkdebug(pc_debugger, ast_source):
    # compile debug instructions
    # (this is dead code -- CMC 2025-05-08)
    i = TaggedInstruction("DEBUG", ast_source)
    i.pc_debugger = pc_debugger
    return [i]


def is_label(i):
    return isinstance(i, Label)


def generate_cbor_metadata(
    compiler_metadata: Any,
    runtime_codesize: int,
    runtime_data_segment_lengths: list[int],
    immutables_len: int,
) -> bytes:
    metadata = (
        compiler_metadata,
        runtime_codesize,
        runtime_data_segment_lengths,
        immutables_len,
        {"vyper": version_tuple},
    )
    ret = cbor2.dumps(metadata)
    # append the length of the footer, *including* the length
    # of the length bytes themselves.
    suffix_len = len(ret) + 2
    ret += suffix_len.to_bytes(2, "big")

    return ret


def _runtime_code_offsets(ctor_mem_size, runtime_codelen):
    # we need two numbers to calculate where the runtime code
    # should be copied to in memory (and making sure we don't
    # trample immutables, which are written to during the ctor
    # code): the memory allocated for the ctor and the length
    # of the runtime code.
    # after the ctor has run but before copying runtime code to
    # memory, the layout is
    # | <ctor memory>       | <runtime immutable data section>
    # and after copying runtime code to memory (immediately before
    # returning the runtime code):
    # | <runtime code>      | <runtime immutable data section>
    # since the ctor memory variables and runtime code overlap,
    # we start allocating the data section from
    # `max(ctor_mem_size, runtime_code_size)`

    runtime_code_end = max(ctor_mem_size, runtime_codelen)
    runtime_code_start = runtime_code_end - runtime_codelen

    return runtime_code_start, runtime_code_end


# Calculate the size of PUSH instruction
def calc_push_size(val: int):
    # stupid implementation. this is "slow", but its correctness is
    # obvious verify, as opposed to
    # ```
    # (val.bit_length() + 7) // 8
    #    + (1
    #         if (val > 0 or version_check(begin="shanghai"))
    #      else 0)
    # ```
    return len(PUSH(val))


# temporary optimization to handle stack items for return sequences
# like `return return_ofst return_len`. this is kind of brittle because
# it assumes the arguments are already on the stack, to be replaced
# by better liveness analysis.
# NOTE: modifies input in-place
def _rewrite_return_sequences(ir_node, label_params=None):
    args = ir_node.args

    if ir_node.value == "return":
        if args[0].value == "ret_ofst" and args[1].value == "ret_len":
            ir_node.args[0].value = "pass"
            ir_node.args[1].value = "pass"
    if ir_node.value == "exit_to":
        # handle exit from private function
        if args[0].value == "return_pc":
            ir_node.value = "jump"
            args[0].value = "pass"
        else:
            # handle jump to cleanup
            ir_node.value = "seq"

            _t = ["seq"]
            if "return_buffer" in label_params:
                _t.append(["pop", "pass"])

            dest = args[0].value
            # works for both internal and external exit_to
            more_args = ["pass" if t.value == "return_pc" else t for t in args[1:]]
            _t.append(["goto", dest] + more_args)
            ir_node.args = IRnode.from_list(_t, ast_source=ir_node.ast_source).args

    if ir_node.value == "label":
        label_params = set(t.value for t in ir_node.args[1].args)

    for t in args:
        _rewrite_return_sequences(t, label_params)


# a string (assembly instruction) but with additional metadata from the source code
class TaggedInstruction(str):
    def __new__(cls, sstr, *args, **kwargs):
        return super().__new__(cls, sstr)

    def __init__(self, sstr, ast_source=None, error_msg=None):
        self.error_msg = error_msg
        self.pc_debugger = False

        self.ast_source = ast_source


##############################
# IRnode to assembly
##############################


# external entry point to `IRnode.compile_to_assembly()`
def compile_to_assembly(
    code: IRnode,
    optimize: OptimizationLevel = OptimizationLevel.GAS,
    compiler_metadata: Optional[Any] = None,
):
    """
    Parameters:
        code: IRnode to compile
        optimize: Optimization level
        compiler_metadata:
            any compiler metadata to add as the final data segment. pass
            `None` to indicate no metadata to be added (should always
            be `None` for runtime code). the value is opaque, and will be
            passed directly to `cbor2.dumps()`.
    """
    # don't mutate the ir since the original might need to be output, e.g. `-f ir,asm`
    code = copy.deepcopy(code)
    _rewrite_return_sequences(code)

    res = _IRnodeLowerer(optimize, compiler_metadata).compile_to_assembly(code)

    if optimize != OptimizationLevel.NONE:
        optimize_assembly(res)
    return res


# TODO: move all these assembly data structures to own module, like
# vyper.evm.assembly
AssemblyInstruction = (
    str | TaggedInstruction | int | PUSHLABEL | Label | PUSH_OFST | DATA_ITEM | DataHeader | CONST
)


class _IRnodeLowerer:
    # map from variable names to height in stack
    withargs: dict[str, int]

    # set of all existing labels in the IRnodes
    existing_labels: set[str]

    # break destination when inside loops
    # continue_dest, break_dest, height
    break_dest: tuple[Label, Label, int]

    # current height in stack
    height: int

    code_instructions: list[AssemblyInstruction]
    data_segments: list[list[AssemblyInstruction]]

    optimize: OptimizationLevel

    symbol_counter: int = 0

    def __init__(self, optimize: OptimizationLevel = OptimizationLevel.GAS, compiler_metadata=None):
        self.optimize = optimize
        self.compiler_metadata = compiler_metadata

    def compile_to_assembly(self, code):
        self.withargs = {}
        self.existing_labels = set()
        self.break_dest = None
        self.height = 0

        self.global_revert_label = None

        self.data_segments = []
        self.freeze_data_segments = False

        ret = self._compile_r(code, height=0)

        # append postambles before data segments
        ret.extend(self._create_postambles())

        for data in self.data_segments:
            ret.extend(self._compile_data_segment(data))

        return ret

    @contextlib.contextmanager
    def modify_breakdest(self, continue_dest: Label, exit_dest: Label, height: int):
        tmp = self.break_dest
        try:
            self.break_dest = continue_dest, exit_dest, height
            yield
        finally:
            self.break_dest = tmp

    def mksymbol(self, name: str) -> Label:
        self.symbol_counter += 1

        return Label(f"{name}_{self.symbol_counter}")

    def _data_ofst_of(
        self, symbol: Label | CONSTREF, ofst: IRnode, height: int
    ) -> list[AssemblyInstruction]:
        # e.g. PUSHOFST foo 32
        assert isinstance(symbol, (Label, CONSTREF)), symbol

        if isinstance(ofst.value, int):
            # resolve at compile time using magic PUSH_OFST op
            return [PUSH_OFST(symbol, ofst.value)]

        # if we can't resolve at compile time, resolve at runtime
        pushsym: PUSHLABEL | PUSH_OFST
        if isinstance(symbol, Label):
            pushsym = PUSHLABEL(symbol)
        else:
            # magic for mem syms
            assert isinstance(symbol, CONSTREF)  # clarity
            # we don't have a PUSHCONST instruction, use PUSH_OFST with ofst of 0
            pushsym = PUSH_OFST(symbol, 0)

        ofst_asm = self._compile_r(ofst, height)
        return ofst_asm + [pushsym, "ADD"]

    def _compile_r(self, code: IRnode, height: int) -> list[AssemblyInstruction]:
        asm = self._step_r(code, height)
        # CMC 2025-05-08 this is O(n^2).. :'(
        for i, item in enumerate(asm):
            if isinstance(item, str) and not isinstance(item, TaggedInstruction):
                asm[i] = TaggedInstruction(item, code.ast_source, code.error_msg)
        return asm

    def _step_r(self, code: IRnode, height: int) -> list[AssemblyInstruction]:
        def _height_of(varname):
            ret = height - self.withargs[varname]
            if ret > 16:  # pragma: nocover
                raise Exception("With statement too deep")
            return ret

        if isinstance(code.value, str) and code.value.upper() in get_opcodes():
            o = []
            for i, c in enumerate(reversed(code.args)):
                o.extend(self._compile_r(c, height + i))
            o.append(code.value.upper())
            return o

        # Numbers
        if isinstance(code.value, int):
            if code.value < -(2**255):  # pragma: nocover
                raise Exception(f"Value too low: {code.value}")
            elif code.value >= 2**256:  # pragma: nocover
                raise Exception(f"Value too high: {code.value}")
            return PUSH(code.value % 2**256)

        # Variables connected to with statements
        if isinstance(code.value, str) and code.value in self.withargs:
            return ["DUP" + str(_height_of(code.value))]

        # Setting variables connected to with statements
        if code.value == "set":
            varname = code.args[0].value
            assert isinstance(varname, str)
            if len(code.args) != 2 or varname not in self.withargs:
                raise Exception("Set expects two arguments, the first being a stack variable")
            # TODO: use _height_of
            if height - self.withargs[varname] > 16:
                raise Exception("With statement too deep")
            swap_instr = "SWAP" + str(height - self.withargs[varname])
            return self._compile_r(code.args[1], height) + [swap_instr, "POP"]

        # Pass statements
        # TODO remove "dummy"; no longer needed
        if code.value in ("pass", "dummy"):
            return []

        # "mload" from data section of the currently executing code
        if code.value == "dload":
            loc = code.args[0]

            o = []
            # codecopy 32 bytes to FREE_VAR_SPACE, then mload from FREE_VAR_SPACE
            o.extend(PUSH(32))

            o.extend(self._data_ofst_of(Label("code_end"), loc, height + 1))

            o.extend(PUSH(MemoryPositions.FREE_VAR_SPACE) + ["CODECOPY"])
            o.extend(PUSH(MemoryPositions.FREE_VAR_SPACE) + ["MLOAD"])
            return o

        # batch copy from data section of the currently executing code to memory
        # (probably should have named this dcopy but oh well)
        if code.value == "dloadbytes":
            dst = code.args[0]
            src = code.args[1]
            len_ = code.args[2]

            o = []
            o.extend(self._compile_r(len_, height))
            o.extend(self._data_ofst_of(Label("code_end"), src, height + 1))
            o.extend(self._compile_r(dst, height + 2))
            o.extend(["CODECOPY"])
            return o

        # "mload" from the data section of (to-be-deployed) runtime code
        if code.value == "iload":
            loc = code.args[0]

            o = []
            o.extend(self._data_ofst_of(CONSTREF("mem_deploy_end"), loc, height))
            o.append("MLOAD")

            return o

        # "mstore" to the data section of (to-be-deployed) runtime code
        if code.value == "istore":
            loc = code.args[0]
            val = code.args[1]

            o = []
            o.extend(self._compile_r(val, height))
            o.extend(self._data_ofst_of(CONSTREF("mem_deploy_end"), loc, height + 1))
            o.append("MSTORE")

            return o

        # batch copy from memory to the data section of runtime code
        if code.value == "istorebytes":
            raise Exception("unimplemented")

        # If statements (2 arguments, ie. if x: y)
        if code.value == "if" and len(code.args) == 2:
            o = []
            o.extend(self._compile_r(code.args[0], height))
            end_symbol = self.mksymbol("join")
            o.extend(["ISZERO", *JUMPI(end_symbol)])
            o.extend(self._compile_r(code.args[1], height))
            o.extend([end_symbol])
            return o

        # If statements (3 arguments, ie. if x: y, else: z)
        if code.value == "if" and len(code.args) == 3:
            o = []
            o.extend(self._compile_r(code.args[0], height))
            mid_symbol = self.mksymbol("else")
            end_symbol = self.mksymbol("join")
            o.extend(["ISZERO", *JUMPI(mid_symbol)])
            o.extend(self._compile_r(code.args[1], height))
            o.extend([*JUMP(end_symbol), mid_symbol])
            o.extend(self._compile_r(code.args[2], height))
            o.extend([end_symbol])
            return o

        # repeat(counter_location, start, rounds, rounds_bound, body)
        # basically a do-while loop:
        #
        # assert(rounds <= rounds_bound)
        # if (rounds > 0) {
        #   do {
        #     body;
        #   } while (++i != start + rounds)
        # }
        if code.value == "repeat":
            o = []
            if len(code.args) != 5:  # pragma: nocover
                raise CompilerPanic("bad number of repeat args")

            i_name = code.args[0]
            start = code.args[1]
            rounds = code.args[2]
            rounds_bound = code.args[3]
            body = code.args[4]

            assert isinstance(i_name.value, str)  # help mypy

            entry_dest = self.mksymbol("loop_start")
            continue_dest = self.mksymbol("loop_continue")
            exit_dest = self.mksymbol("loop_exit")

            # stack: []
            o.extend(self._compile_r(start, height))

            o.extend(self._compile_r(rounds, height + 1))

            # stack: i

            # assert rounds <= round_bound
            if rounds != rounds_bound:
                # stack: i, rounds
                o.extend(self._compile_r(rounds_bound, height + 2))
                # stack: i, rounds, rounds_bound
                # assert 0 <= rounds <= rounds_bound (for rounds_bound < 2**255)
                # TODO this runtime assertion shouldn't fail for
                # internally generated repeats.
                o.extend(["DUP2", "GT"] + self._assert_false())

                # stack: i, rounds
                # if (0 == rounds) { goto end_dest; }
                o.extend(["DUP1", "ISZERO", *JUMPI(exit_dest)])

            # stack: start, rounds
            if start.value != 0:
                o.extend(["DUP2", "ADD"])

            # stack: i, exit_i
            o.extend(["SWAP1"])

            if i_name.value in self.withargs:  # pragma: nocover
                raise CompilerPanic(f"shadowed loop variable {i_name}")
            self.withargs[i_name.value] = height + 1

            # stack: exit_i, i
            o.extend([entry_dest])

            with self.modify_breakdest(exit_dest, continue_dest, height + 2):
                o.extend(self._compile_r(body, height + 2))

            del self.withargs[i_name.value]

            # clean up any stack items left by body
            o.extend(["POP"] * body.valency)

            # stack: exit_i, i
            # increment i:
            o.extend([continue_dest, "PUSH1", 1, "ADD"])

            # stack: exit_i, i+1 (new_i)
            # if (exit_i != new_i) { goto entry_dest }
            o.extend(["DUP2", "DUP2", "XOR", *JUMPI(entry_dest)])
            o.extend([exit_dest, "POP", "POP"])

            return o

        # Continue to the next iteration of the for loop
        if code.value == "continue":
            if not self.break_dest:  # pragma: nocover
                raise CompilerPanic("Invalid break")
            _dest, continue_dest, _break_height = self.break_dest
            return [*JUMP(continue_dest)]

        # Break from inside a for loop
        if code.value == "break":
            if not self.break_dest:  # pragma: nocover
                raise CompilerPanic("Invalid break")
            dest, _continue_dest, break_height = self.break_dest

            n_local_vars = height - break_height
            # clean up any stack items declared in the loop body
            cleanup_local_vars = ["POP"] * n_local_vars
            return cleanup_local_vars + [*JUMP(dest)]

        # Break from inside one or more for loops prior to a return statement inside the loop
        if code.value == "cleanup_repeat":
            if not self.break_dest:  # pragma: nocover
                raise CompilerPanic("Invalid break")
            # clean up local vars and internal loop vars
            _, _, break_height = self.break_dest
            # except don't pop label params
            if "return_buffer" in self.withargs:
                break_height -= 1
            if "return_pc" in self.withargs:
                break_height -= 1
            return ["POP"] * break_height

        # With statements
        if code.value == "with":
            varname = code.args[0].value
            assert isinstance(varname, str)

            o = []
            o.extend(self._compile_r(code.args[1], height))
            old = self.withargs.get(varname, None)
            self.withargs[varname] = height
            o.extend(self._compile_r(code.args[2], height + 1))
            if code.args[2].valency:
                o.extend(["SWAP1", "POP"])
            else:
                o.extend(["POP"])

            if old is not None:
                self.withargs[varname] = old
            else:
                del self.withargs[varname]

            return o

        # runtime statement (used to deploy runtime code)
        if code.value == "deploy":
            # used to calculate where to copy the runtime code to memory
            memsize = code.args[0].value
            ir = code.args[1]
            immutables_len = code.args[2].value
            assert isinstance(memsize, int), "non-int memsize"
            assert isinstance(immutables_len, int), "non-int immutables_len"

            runtime_assembly = _IRnodeLowerer(
                self.optimize, self.compiler_metadata
            ).compile_to_assembly(ir)

            if self.optimize != OptimizationLevel.NONE:
                optimize_assembly(runtime_assembly)

            runtime_data_segment_lengths = get_data_segment_lengths(runtime_assembly)

            runtime_bytecode, _ = assembly_to_evm(runtime_assembly)

            runtime_begin = Label("runtime_begin")
            o = []

            runtime_codesize = len(runtime_bytecode)

            mem_deploy_start, mem_deploy_end = _runtime_code_offsets(memsize, runtime_codesize)

            # COPY the code to memory for deploy
            o.extend(
                [
                    *PUSH(runtime_codesize),
                    PUSHLABEL(runtime_begin),
                    *PUSH(mem_deploy_start),
                    "CODECOPY",
                ]
            )

            o.append(CONST("mem_deploy_end", mem_deploy_end))

            # calculate the len of runtime code + immutables size
            amount_to_return = runtime_codesize + immutables_len
            o.extend([*PUSH(amount_to_return)])  # stack: len
            o.extend([*PUSH(mem_deploy_start)])  # stack: len mem_ofst

            o.extend(["RETURN"])

            self.data_segments.append([DataHeader(runtime_begin), DATA_ITEM(runtime_bytecode)])

            if self.compiler_metadata is not None:
                # we should issue the cbor-encoded metadata.
                bytecode_suffix = generate_cbor_metadata(
                    self.compiler_metadata,
                    runtime_codesize,
                    runtime_data_segment_lengths,
                    immutables_len,
                )

                segment: list[AssemblyInstruction] = [DataHeader(Label("cbor_metadata"))]
                segment.append(DATA_ITEM(bytecode_suffix))
                self.data_segments.append(segment)

            return o

        # Seq (used to piece together multiple statements)
        if code.value == "seq":
            o = []
            for arg in code.args:
                o.extend(self._compile_r(arg, height))
                if arg.valency == 1 and arg != code.args[-1]:
                    o.append("POP")
            return o

        # Seq without popping.
        # unreachable keyword produces INVALID opcode
        if code.value == "assert_unreachable":
            o = self._compile_r(code.args[0], height)
            end_symbol = self.mksymbol("reachable")
            o.extend([*JUMPI(end_symbol), "INVALID", end_symbol])
            return o

        # Assert (if false, exit)
        if code.value == "assert":
            o = self._compile_r(code.args[0], height)
            o.extend(["ISZERO"])
            o.extend(self._assert_false())
            return o

        # SHA3 a 64 byte value
        if code.value == "sha3_64":
            o = self._compile_r(code.args[0], height)
            o.extend(self._compile_r(code.args[1], height + 1))
            o.extend(
                [
                    *PUSH(MemoryPositions.FREE_VAR_SPACE2),
                    "MSTORE",
                    *PUSH(MemoryPositions.FREE_VAR_SPACE),
                    "MSTORE",
                    *PUSH(64),
                    *PUSH(MemoryPositions.FREE_VAR_SPACE),
                    "SHA3",
                ]
            )
            return o

        if code.value == "select":
            # b ^ ((a ^ b) * cond) where cond is 1 or 0
            # let t = a ^ b
            cond = code.args[0]
            a = code.args[1]
            b = code.args[2]

            o = []
            o.extend(self._compile_r(b, height))
            o.extend(self._compile_r(a, height + 1))
            # stack: b a
            o.extend(["DUP2", "XOR"])
            # stack: b t
            o.extend(self._compile_r(cond, height + 2))
            # stack: b t cond
            o.extend(["MUL", "XOR"])

            # stack: b ^ (t * cond)
            return o

        # <= operator
        if code.value == "le":
            expanded_ir = IRnode.from_list(["iszero", ["gt", code.args[0], code.args[1]]])
            return self._compile_r(expanded_ir, height)

        # >= operator
        if code.value == "ge":
            expanded_ir = IRnode.from_list(["iszero", ["lt", code.args[0], code.args[1]]])
            return self._compile_r(expanded_ir, height)
        # <= operator
        if code.value == "sle":
            expanded_ir = IRnode.from_list(["iszero", ["sgt", code.args[0], code.args[1]]])
            return self._compile_r(expanded_ir, height)
        # >= operator
        if code.value == "sge":
            expanded_ir = IRnode.from_list(["iszero", ["slt", code.args[0], code.args[1]]])
            return self._compile_r(expanded_ir, height)

        # != operator
        if code.value == "ne":
            expanded_ir = IRnode.from_list(["iszero", ["eq", code.args[0], code.args[1]]])
            return self._compile_r(expanded_ir, height)

        # e.g. 95 -> 96, 96 -> 96, 97 -> 128
        if code.value == "ceil32":
            # floor32(x) = x - x % 32 == x & 0b11..100000 == x & (~31)
            # ceil32(x) = floor32(x + 31) == (x + 31) & (~31)
            x = code.args[0]
            expanded_ir = IRnode.from_list(["and", ["add", x, 31], ["not", 31]])
            return self._compile_r(expanded_ir, height)

        if code.value == "data":
            assert isinstance(code.args[0].value, str)  # help mypy

            data_header = DataHeader(Label(code.args[0].value))
            data_items = []

            for c in code.args[1:]:
                if isinstance(c.value, bytes):
                    data_items.append(DATA_ITEM(c.value))
                elif isinstance(c, IRnode):
                    assert c.value == "symbol"
                    assert len(c.args) == 1
                    assert isinstance(c.args[0].value, str), (type(c.args[0].value), c)
                    data_items.append(DATA_ITEM(Label(c.args[0].value)))
                else:  # pragma: nocover
                    raise ValueError(f"Invalid data: {type(c)} {c}")

            self.data_segments.append([data_header, *data_items])
            return []

        # jump to a symbol, and push variable # of arguments onto stack
        if code.value == "goto":
            o = []
            for i, c in enumerate(reversed(code.args[1:])):
                o.extend(self._compile_r(c, height + i))
            target = code.args[0].value
            assert isinstance(target, str)  # help mypy
            o.extend([*JUMP(Label(target))])
            return o

        if code.value == "djump":
            o = []
            # "djump" compiles to a raw EVM jump instruction
            jump_target = code.args[0]
            o.extend(self._compile_r(jump_target, height))
            o.append("JUMP")
            return o
        # push a literal symbol
        if code.value == "symbol":
            label = code.args[0].value
            assert isinstance(label, str)
            return [PUSHLABEL(Label(label))]

        # set a symbol as a location.
        if code.value == "label":
            label_name = code.args[0].value
            assert isinstance(label_name, str)

            if label_name in self.existing_labels:  # pragma: nocover
                raise Exception(f"Label with name {label_name} already exists!")
            else:
                self.existing_labels.add(label_name)

            if code.args[1].value != "var_list":  # pragma: nocover
                raise CodegenPanic("2nd arg to label must be var_list")
            var_args = code.args[1].args

            body = code.args[2]

            # new scope
            height = 0
            old_withargs = self.withargs

            self.withargs = {}

            for arg in reversed(var_args):
                assert isinstance(arg.value, str)  # sanity
                self.withargs[arg.value] = height
                height += 1

            body_asm = self._compile_r(body, height)
            # pop_scoped_vars = ["POP"] * height
            # for now, _rewrite_return_sequences forces
            # label params to be consumed implicitly
            pop_scoped_vars: list = []

            self.withargs = old_withargs

            return [Label(label_name)] + body_asm + pop_scoped_vars

        if code.value == "unique_symbol":
            symbol = code.args[0].value
            assert isinstance(symbol, str)

            if symbol in self.existing_labels:  # pragma: nocover
                raise Exception(f"symbol {symbol} already exists!")
            else:
                self.existing_labels.add(symbol)

            return []

        if code.value == "exit_to":
            # currently removed by _rewrite_return_sequences
            raise CodegenPanic("exit_to not implemented yet!")

        # inject debug opcode.
        if code.value == "debugger":
            return mkdebug(pc_debugger=False, ast_source=code.ast_source)

        # inject debug opcode.
        if code.value == "pc_debugger":
            return mkdebug(pc_debugger=True, ast_source=code.ast_source)

        raise CompilerPanic(f"invalid IRnode: {type(code)} {code}")  # pragma: no cover

    def _create_postambles(self):
        ret = []
        # for some reason there might not be a STOP at the end of asm_ops.
        # (generally vyper programs will have it but raw IR might not).
        ret.append("STOP")

        # common revert block
        if self.global_revert_label is not None:
            ret.extend([self.global_revert_label, *PUSH(0), "DUP1", "REVERT"])

        return ret

    def _compile_data_segment(
        self, segment: list[AssemblyInstruction]
    ) -> list[AssemblyInstruction]:
        return segment

    def _assert_false(self):
        if self.global_revert_label is None:
            self.global_revert_label = self.mksymbol("revert")
        # use a shared failure block for common case of assert(x).
        return JUMPI(self.global_revert_label)


##############################
# assembly to evm utils
##############################


def note_line_num(line_number_map, pc, item):
    # Record AST attached to pc
    if isinstance(item, TaggedInstruction):
        if (ast_node := item.ast_source) is not None:
            ast_node = ast_node.get_original_node()
            if hasattr(ast_node, "node_id"):
                line_number_map["pc_raw_ast_map"][pc] = ast_node

        if item.error_msg is not None:
            line_number_map["error_map"][pc] = item.error_msg

    note_breakpoint(line_number_map, pc, item)


# NOTE: this is dead code, we don't emit DEBUG anymore.
def note_breakpoint(line_number_map, pc, item):
    # Record line number attached to pc
    if item == "DEBUG":
        # Is PC debugger, create PC breakpoint.
        if item.pc_debugger:
            line_number_map["pc_breakpoints"].add(pc)
        # Create line number breakpoint.
        else:
            line_number_map["breakpoints"].add(item.lineno + 1)


##############################
# assembly optimizer
##############################

_TERMINAL_OPS = ("JUMP", "RETURN", "REVERT", "STOP", "INVALID")


def _prune_unreachable_code(assembly):
    # delete code between terminal ops and JUMPDESTS as those are
    # unreachable
    changed = False
    i = 0
    while i < len(assembly) - 1:
        if assembly[i] in _TERMINAL_OPS:
            # find the next jumpdest or data section
            for j in range(i + 1, len(assembly)):
                next_is_reachable = isinstance(assembly[j], (Label, DataHeader))
                if next_is_reachable:
                    break
            else:
                # fixup an off-by-one if we made it to the end of the assembly
                # without finding an jumpdest or sublist
                j = len(assembly)
            changed |= j > i + 1
            del assembly[i + 1 : j]

        i += 1

    return changed


def _prune_inefficient_jumps(assembly):
    # prune sequences `PUSHLABEL x JUMP LABEL x` to `LABEL x`
    changed = False
    i = 0
    while i < len(assembly) - 2:
        if (
            isinstance(assembly[i], PUSHLABEL)
            and assembly[i + 1] == "JUMP"
            and is_label(assembly[i + 2])
            and assembly[i + 2] == assembly[i].label
        ):
            # delete PUSHLABEL x JUMP
            changed = True
            del assembly[i : i + 2]
        else:
            i += 1

    return changed


def _optimize_inefficient_jumps(assembly):
    # optimize sequences
    # `PUSHLABEL common JUMPI PUSHLABEL x JUMP LABEL common`
    # to `ISZERO PUSHLABEL x JUMPI LABEL common`
    changed = False
    i = 0
    while i < len(assembly) - 4:
        if (
            isinstance(assembly[i], PUSHLABEL)
            and assembly[i + 1] == "JUMPI"
            and isinstance(assembly[i + 2], PUSHLABEL)
            and assembly[i + 3] == "JUMP"
            and isinstance(assembly[i + 4], Label)
            and assembly[i].label == assembly[i + 4]
        ):
            changed = True
            assembly[i] = "ISZERO"
            assembly[i + 1] = assembly[i + 2]
            assembly[i + 2] = "JUMPI"
            del assembly[i + 3 : i + 4]
        else:
            i += 1

    return changed


def _merge_jumpdests(assembly):
    # When we have multiple JUMPDESTs in a row, or when a JUMPDEST
    # is immediately followed by another JUMP, we can skip the
    # intermediate jumps.
    # (Usually a chain of JUMPs is created by a nested block,
    # or some nested if statements.)
    changed = False
    i = 0
    while i < len(assembly) - 2:
        if is_label(assembly[i]):
            current_symbol = assembly[i]
            if is_label(assembly[i + 1]):
                # LABEL x LABEL y
                # replace all instances of PUSHLABEL x with PUSHLABEL y
                # (could also remove PUSH_OFST and DATA_ITEM, but doesn't
                #  affect correctness)
                new_symbol = assembly[i + 1]
                if new_symbol != current_symbol:
                    for j in range(len(assembly)):
                        if (
                            isinstance(assembly[j], PUSHLABEL)
                            and assembly[j].label == current_symbol
                        ):
                            assembly[j].label = new_symbol
                            changed = True
            elif isinstance(assembly[i + 1], PUSHLABEL) and assembly[i + 2] == "JUMP":
                # LABEL x PUSHLABEL y JUMP
                # replace all instances of PUSHLABEL x with PUSHLABEL y
                # (could also remove PUSH_OFST and DATA_ITEM, but doesn't
                #  affect correctness)
                new_symbol = assembly[i + 1].label
                for j in range(len(assembly)):
                    if isinstance(assembly[j], PUSHLABEL) and assembly[j].label == current_symbol:
                        assembly[j].label = new_symbol
                        changed = True

        i += 1

    return changed


_RETURNS_ZERO_OR_ONE = {
    "LT",
    "GT",
    "SLT",
    "SGT",
    "EQ",
    "ISZERO",
    "CALL",
    "STATICCALL",
    "CALLCODE",
    "DELEGATECALL",
}


def _merge_iszero(assembly):
    changed = False

    i = 0
    # list of opcodes that return 0 or 1
    while i < len(assembly) - 2:
        if (
            isinstance(assembly[i], str)
            and assembly[i] in _RETURNS_ZERO_OR_ONE
            and assembly[i + 1 : i + 3] == ["ISZERO", "ISZERO"]
        ):
            changed = True
            # drop the extra iszeros
            del assembly[i + 1 : i + 3]
        else:
            i += 1
    i = 0
    while i < len(assembly) - 3:
        # ISZERO ISZERO could map truthy to 1,
        # but it could also just be a no-op before JUMPI.
        if (
            assembly[i : i + 2] == ["ISZERO", "ISZERO"]
            and isinstance(assembly[i + 2], PUSHLABEL)
            and assembly[i + 3] == "JUMPI"
        ):
            changed = True
            del assembly[i : i + 2]
        else:
            i += 1

    return changed


def _prune_unused_jumpdests(assembly):
    changed = False

    used_jumpdests: set[Label] = set()

    # find all used jumpdests
    for item in assembly:
        if isinstance(item, PUSHLABEL):
            used_jumpdests.add(item.label)

        if isinstance(item, PUSH_OFST) and isinstance(item.label, Label):
            used_jumpdests.add(item.label)

        if isinstance(item, DATA_ITEM) and isinstance(item.data, Label):
            # add symbols used in data sections as they are likely
            # used for a jumptable.
            used_jumpdests.add(item.data)

    # delete jumpdests that aren't used
    i = 0
    while i < len(assembly):
        if is_label(assembly[i]) and assembly[i] not in used_jumpdests:
            changed = True
            del assembly[i]
        else:
            i += 1

    return changed


def _stack_peephole_opts(assembly):
    changed = False
    i = 0
    while i < len(assembly) - 2:
        if assembly[i : i + 3] == ["DUP1", "SWAP2", "SWAP1"]:
            changed = True
            del assembly[i + 2]
            assembly[i] = "SWAP1"
            assembly[i + 1] = "DUP2"
            continue
        # usually generated by with statements that return their input like
        # (with x (...x))
        if assembly[i : i + 3] == ["DUP1", "SWAP1", "POP"]:
            # DUP1 SWAP1 POP == no-op
            changed = True
            del assembly[i : i + 3]
            continue
        # usually generated by nested with statements that don't return like
        # (with x (with y ...))
        if assembly[i : i + 3] == ["SWAP1", "POP", "POP"]:
            # SWAP1 POP POP == POP POP
            changed = True
            del assembly[i]
            continue
        if (
            isinstance(assembly[i], str)
            and assembly[i].startswith("SWAP")
            and assembly[i] == assembly[i + 1]
        ):
            changed = True
            del assembly[i : i + 2]
        if assembly[i] == "SWAP1" and str(assembly[i + 1]).lower() in COMMUTATIVE_OPS:
            changed = True
            del assembly[i]
        if assembly[i] == "DUP1" and assembly[i + 1] == "SWAP1":
            changed = True
            del assembly[i + 1]
        i += 1

    return changed


# optimize assembly, in place
def optimize_assembly(assembly):
    for _ in range(1024):
        changed = False

        changed |= _prune_unreachable_code(assembly)
        changed |= _merge_iszero(assembly)
        changed |= _merge_jumpdests(assembly)
        changed |= _prune_inefficient_jumps(assembly)
        changed |= _optimize_inefficient_jumps(assembly)
        changed |= _prune_unused_jumpdests(assembly)
        changed |= _stack_peephole_opts(assembly)

        if not changed:
            return

    raise CompilerPanic("infinite loop detected during assembly reduction")  # pragma: nocover


SYMBOL_SIZE = 2  # size of a PUSH instruction for a code symbol


# predict what length of an assembly [data] node will be in bytecode
def get_data_segment_lengths(assembly: list[AssemblyInstruction]) -> list[int]:
    ret = []
    for item in assembly:
        if isinstance(item, DataHeader):
            ret.append(0)
            continue
        if len(ret) == 0:
            # haven't yet seen a data header
            continue
        assert isinstance(item, DATA_ITEM)
        if is_label(item.data):
            ret[-1] += SYMBOL_SIZE
        elif isinstance(item.data, bytes):
            ret[-1] += len(item.data)
        else:  # pragma: nocover
            raise ValueError(f"invalid data {type(item)} {item}")

    return ret


##############################
# assembly to evm bytecode
##############################


def _compile_data_item(item: DATA_ITEM, symbol_map: dict[Label, int]) -> bytes:
    if isinstance(item.data, bytes):
        return item.data
    if isinstance(item.data, Label):
        symbolbytes = symbol_map[item.data].to_bytes(SYMBOL_SIZE, "big")
        return symbolbytes

    raise CompilerPanic(f"Invalid data {type(item.data)}, {item.data}")  # pragma: nocover


T = TypeVar("T")


def _add_to_symbol_map(symbol_map: dict[T, int], item: T, value: int):
    if item in symbol_map:  # pragma: nocover
        raise CompilerPanic(f"duplicate label: {item}")
    symbol_map[item] = value


def assembly_to_evm(assembly: list[AssemblyInstruction]) -> tuple[bytes, dict[str, Any]]:
    """
    Generate bytecode and source map from assembly

    Returns:
        bytecode: bytestring of the EVM bytecode
        source_map: source map dict that gets output for the user
    """
    # This API might seem a bit strange, but it's backwards compatible
    symbol_map, const_map, source_map = resolve_symbols(assembly)
    bytecode = _assembly_to_evm(assembly, symbol_map, const_map)
    return bytecode, source_map


# resolve symbols in assembly
def resolve_symbols(
    assembly: list[AssemblyInstruction],
) -> tuple[dict[Label, int], dict[CONSTREF, int], dict[str, Any]]:
    """
    Construct symbol map from assembly list

    Returns:
        symbol_map: dict from labels to values
        const_map: dict from CONSTREFs to values
        source_map: source map dict that gets output for the user
    """
    source_map: dict[str, Any] = {
        "breakpoints": OrderedSet(),
        "pc_breakpoints": OrderedSet(),
        "pc_jump_map": {0: "-"},
        "pc_raw_ast_map": {},
        "error_map": {},
    }

    symbol_map: dict[Label, int] = {}
    const_map: dict[CONSTREF, int] = {}

    pc: int = 0

    # resolve constants
    for item in assembly:
        if isinstance(item, CONST):
            # should this be merged into the symbol map?
            _add_to_symbol_map(const_map, CONSTREF(item.name), item.value)

    # resolve labels (i.e. JUMPDEST locations) to actual code locations,
    # and simultaneously build the source map.
    for i, item in enumerate(assembly):
        # add it to the source map
        note_line_num(source_map, pc, item)

        # update pc_jump_map
        if item == "JUMP":
            assert i != 0  # otherwise we can get assembly[-1]
            last = assembly[i - 1]
            if isinstance(last, PUSHLABEL) and last.label.label.startswith("internal"):
                if last.label.label.endswith("cleanup"):
                    # exit an internal function
                    source_map["pc_jump_map"][pc] = "o"
                else:
                    # enter an internal function
                    source_map["pc_jump_map"][pc] = "i"
            else:
                # everything else
                source_map["pc_jump_map"][pc] = "-"
        elif item in ("JUMPI", "JUMPDEST"):
            source_map["pc_jump_map"][pc] = "-"

        if item == "DEBUG":
            continue  # "debug" opcode does not go into bytecode

        if isinstance(item, CONST):
            continue  # CONST declarations do not go into bytecode

        # update pc
        if isinstance(item, Label):
            _add_to_symbol_map(symbol_map, item, pc)
            pc += 1  # jumpdest

        elif isinstance(item, DataHeader):
            # Don't increment pc as the symbol itself doesn't go into code
            _add_to_symbol_map(symbol_map, item.label, pc)

        elif isinstance(item, PUSHLABEL):
            pc += SYMBOL_SIZE + 1  # PUSH2 highbits lowbits

        elif isinstance(item, PUSH_OFST):
            assert isinstance(item.ofst, int), item
            # [PUSH_OFST, (Label foo), bar] -> PUSH2 (foo+bar)
            # [PUSH_OFST, _mem_foo, bar] -> PUSHN (foo+bar)
            if isinstance(item.label, Label):
                pc += SYMBOL_SIZE + 1  # PUSH2 highbits lowbits
            elif isinstance(item.label, CONSTREF):
                const = const_map[item.label]
                val = const + item.ofst
                pc += calc_push_size(val)
            else:  # pragma: nocover
                raise CompilerPanic(f"invalid ofst {item.label}")

        elif isinstance(item, DATA_ITEM):
            if isinstance(item.data, Label):
                pc += SYMBOL_SIZE
            else:
                assert isinstance(item.data, bytes)
                pc += len(item.data)
        elif isinstance(item, int):
            assert 0 <= item < 256
            pc += 1
        else:
            assert isinstance(item, str) and item in get_opcodes(), item
            pc += 1

    source_map["breakpoints"] = list(source_map["breakpoints"])
    source_map["pc_breakpoints"] = list(source_map["pc_breakpoints"])

    # magic -- probably the assembler should actually add this label
    _add_to_symbol_map(symbol_map, Label("code_end"), pc)

    return symbol_map, const_map, source_map


# helper function
def _compile_push_instruction(assembly: list[AssemblyInstruction]) -> bytes:
    push_mnemonic = assembly[0]
    assert isinstance(push_mnemonic, str) and push_mnemonic.startswith("PUSH")
    push_instr = PUSH_OFFSET + int(push_mnemonic[4:])
    ret = [push_instr]

    for item in assembly[1:]:
        assert isinstance(item, int)
        ret.append(item)
    return bytes(ret)


def _assembly_to_evm(
    assembly: list[AssemblyInstruction],
    symbol_map: dict[Label, int],
    const_map: dict[CONSTREF, int],
) -> bytes:
    """
    Assembles assembly into EVM bytecode

    Parameters:
        assembly: list of asm instructions
        symbol_map: dict from labels to resolved locations in the code
        const_map: dict from constrefs to their values

    Returns: bytes representing the bytecode
    """
    ret = bytearray()

    # now that all symbols have been resolved, generate bytecode
    # using the symbol map
    for item in assembly:
        if item in ("DEBUG",):
            continue  # skippable opcodes
        elif isinstance(item, CONST):
            continue  # CONST things do not show up in bytecode
        elif isinstance(item, DataHeader):
            continue  # DataHeader does not show up in bytecode

        elif isinstance(item, PUSHLABEL):
            # push a symbol to stack
            label = item.label
            bytecode = _compile_push_instruction(PUSH_N(symbol_map[label], n=SYMBOL_SIZE))
            ret.extend(bytecode)

        elif isinstance(item, Label):
            jumpdest_opcode = get_opcodes()["JUMPDEST"][0]
            assert jumpdest_opcode is not None  # help mypy
            ret.append(jumpdest_opcode)

        elif isinstance(item, PUSH_OFST):
            # PUSH_OFST (LABEL foo) 32
            # PUSH_OFST (const foo) 32
            if isinstance(item.label, Label):
                ofst = symbol_map[item.label] + item.ofst
                bytecode = _compile_push_instruction(PUSH_N(ofst, SYMBOL_SIZE))
            else:
                assert isinstance(item.label, CONSTREF)
                ofst = const_map[item.label] + item.ofst
                bytecode = _compile_push_instruction(PUSH(ofst))

            ret.extend(bytecode)

        elif isinstance(item, int):
            ret.append(item)
        elif isinstance(item, str) and item.upper() in get_opcodes():
            opcode = get_opcodes()[item.upper()][0]
            # TODO: fix signature of get_opcodes()
            assert opcode is not None  # help mypy
            ret.append(opcode)
        elif isinstance(item, DATA_ITEM):
            ret.extend(_compile_data_item(item, symbol_map))
        elif item[:4] == "PUSH":
            ret.append(PUSH_OFFSET + int(item[4:]))
        elif item[:3] == "DUP":
            ret.append(DUP_OFFSET + int(item[3:]))
        elif item[:4] == "SWAP":
            ret.append(SWAP_OFFSET + int(item[4:]))
        else:  # pragma: no cover
            # unreachable
            raise ValueError(f"Weird symbol in assembly: {type(item)} {item}")

    return bytes(ret)
