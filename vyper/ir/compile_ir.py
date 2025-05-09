from __future__ import annotations

import contextlib
import copy
import math
from dataclasses import dataclass

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
        assert isinstance(label, Label)
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
    def __init__(self, label: Label | str, ofst: int):
        # label can be Label or (temporarily) str, until
        # we clean up mem_syms.
        assert isinstance(label, (Label, str))
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
        if isinstance(self.item, bytes):
            return "DATABYTES {self.item}"
        elif isinstance(self.item, Label):
            return "DATALABEL {self.item.label}"

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


def is_symbol(i):
    return isinstance(i, Label)


# basically a pointer but like a symbol in that it gets resolved
# during assembly, but requires up to 4 bytes of space.
# (should only happen in initcode)
def is_mem_sym(i):
    return isinstance(i, str) and i.startswith("_mem_")


def is_ofst(assembly_item):
    return isinstance(assembly_item, PUSH_OFST)


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


# Calculate the size of PUSH instruction we need to handle all
# mem offsets in the code. For instance, if we only see mem symbols
# up to size 256, we can use PUSH1.
def calc_mem_ofst_size(ctor_mem_size):
    return math.ceil(math.log(ctor_mem_size + 1, 256))


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


def compile_to_assembly(code, optimize=OptimizationLevel.GAS):
    # don't overwrite ir since the original might need to be output, e.g. `-f ir,asm`
    code = copy.deepcopy(code)
    _rewrite_return_sequences(code)

    res = _IRnodeLowerer().compile_to_assembly(code)

    if optimize != OptimizationLevel.NONE:
        optimize_assembly(res)
    return res


AssemblyInstruction = str | TaggedInstruction | int | PUSHLABEL | Label | PUSH_OFST


class _IRnodeLowerer:
    # map from variable names to height in stack
    withargs: dict[str, int]

    # set of all existing labels
    existing_labels: set[Label]

    # break destination when inside loops
    # continue_dest, break_dest, height
    break_dest: tuple[Label, Label, int]

    # current height in stack
    height: int

    code_instructions: list[AssemblyInstruction]
    data_segments: list[DataSegment]

    def __init__(self, symbol_counter=0):
        self.symbol_counter = symbol_counter

    def compile_to_assembly(self, code):
        self.withargs = {}
        self.existing_labels = set()
        self.break_dest = None
        self.height = 0

        self.global_revert_label = None

        self.data_segments = []
        self.freeze_data_segments = False

        return self._compile_r(code, height=0)

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

    def _data_ofst_of(self, symbol: str | Label, ofst: IRnode, height) -> list[AssemblyInstruction]:
        # e.g. PUSHOFST foo 32
        assert is_symbol(symbol) or is_mem_sym(symbol), symbol

        if isinstance(ofst.value, int):
            # resolve at compile time using magic PUSH_OFST op
            return [PUSH_OFST(symbol, ofst.value)]

        if isinstance(symbol, Label):
            pushsym = PUSHLABEL(symbol)
        else:
            # magic for mem syms
            assert is_mem_sym(symbol)  # clarity
            pushsym = symbol

        # if we can't resolve at compile time, resolve at runtime
        ofst = self._compile_r(ofst, height)
        return ofst + [pushsym, "ADD"]

    def _compile_r(self, code: IRnode, height: int) -> list[AssemblyInstruction]:
        asm = self._step_r(code, height)
        for i, item in enumerate(asm):
            if isinstance(item, str) and not isinstance(item, TaggedInstruction):
                # CMC 2025-05-08 this is O(n^2).. :'(
                asm[i] = TaggedInstruction(item, code.ast_source, code.error_msg)

        return asm

    def _step_r(self, code: IRnode, height: int) -> list[AssemblyInstruction]:
        def _height_of(varname):
            ret = height - self.withargs[varname]
            if ret > 16:
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
            if code.value < -(2**255):
                raise Exception(f"Value too low: {code.value}")
            elif code.value >= 2**256:
                raise Exception(f"Value too high: {code.value}")

            return PUSH(code.value % 2**256)

        # Variables connected to with statements
        if isinstance(code.value, str) and code.value in self.withargs:
            return ["DUP" + str(_height_of(code.value))]

        # Setting variables connected to with statements
        if code.value == "set":
            if len(code.args) != 2 or code.args[0].value not in self.withargs:
                raise Exception("Set expects two arguments, the first being a stack variable")
            if height - self.withargs[code.args[0].value] > 16:
                raise Exception("With statement too deep")
            swap_instr = "SWAP" + str(height - self.withargs[code.args[0].value])
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

            o.extend(self._data_ofst_of(Label("code_end"), loc, height))

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
            o.extend(self._data_ofst_of("_mem_deploy_end", loc, height))
            o.append("MLOAD")

            return o

        # "mstore" to the data section of (to-be-deployed) runtime code
        if code.value == "istore":
            loc = code.args[0]
            val = code.args[1]

            o = []
            o.extend(self._compile_r(val, height))
            o.extend(self._data_ofst_of("_mem_deploy_end", loc, height + 1))
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
            o.extend(self._compile(code.args[1], height))
            o.extend([*JUMP(end_symbol), mid_symbol])
            o.extend(self._compile(code.args[2], height))
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

            if i_name.value in self.withargs:
                raise CompilerPanic(f"shadowed loop variable {i_name}")
            self.withargs[i_name.value] = height + 1

            # stack: exit_i, i
            o.extend([entry_dest])

            with self.modify_breakdest(exit_dest, continue_dest, height + 2):
                o.extend(self._compile_r(body, height + 2))

            del withargs[i_name.value]

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
            if not self.break_dest:
                raise CompilerPanic("Invalid break")
            _dest, continue_dest, _break_height = self.break_dest
            return [*JUMP(continue_dest)]

        # Break from inside a for loop
        if code.value == "break":
            if not self.break_dest:
                raise CompilerPanic("Invalid break")
            dest, _continue_dest, break_height = self.break_dest

            n_local_vars = height - break_height
            # clean up any stack items declared in the loop body
            cleanup_local_vars = ["POP"] * n_local_vars
            return cleanup_local_vars + [*JUMP(dest)]

        # Break from inside one or more for loops prior to a return statement inside the loop
        if code.value == "cleanup_repeat":
            if not self.break_dest:
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
            o = []
            o.extend(self._compile_r(code.args[1], height))
            old = self.withargs.get(code.args[0].value, None)
            self.withargs[code.args[0].value] = height
            o.extend(self._compile_r(code.args[2], height + 1))
            if code.args[2].valency:
                o.extend(["SWAP1", "POP"])
            else:
                o.extend(["POP"])
            if old is not None:
                self.withargs[code.args[0].value] = old
            else:
                del self.withargs[code.args[0].value]
            return o

        # runtime statement (used to deploy runtime code)
        elif code.value == "deploy":
            memsize = code.args[0].value  # used later to calculate _mem_deploy_start
            ir = code.args[1]
            immutables_len = code.args[2].value
            assert isinstance(memsize, int), "non-int memsize"
            assert isinstance(immutables_len, int), "non-int immutables_len"

            runtime_assembly = _IRnodeLowerer().compile_to_assembly(ir)

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

            # calculate the len of runtime code + immutables size
            amount_to_return = runtime_codesize + immutables_len
            o.extend(*PUSH(amount_to_return))  # stack: len
            o.extend(*PUSH(mem_deploy_start))  # stack: len mem_ofst
            o.extend(["RETURN"])

            o.extend(self._create_postambles())

            for data in self.data_segments:
                o.extend(self._compile_data_segment(data))

            self.freeze_data_segments = True

            # TODO: these two probably not needed
            o.append(CONST("ctor_mem_size", memsize))
            o.append(CONST("immutables_len", immutables_len))

            o.append(CONST("mem_deploy_start", mem_deploy_start))
            o.append(CONST("mem_deploy_end", mem_deploy_end))

            o.append(runtime_begin)

            o.append(DATA_ITEM(runtime_bytecode))

            # maybe not needed
            o.append(Label("runtime_end"))

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

        # SHA3 a single value
        if code.value == "sha3_32":
            # TODO: this should not be emitted anymore.
            o = self._compile_r(code.args[0], height)
            o.extend(
                [
                    *PUSH(MemoryPositions.FREE_VAR_SPACE),
                    "MSTORE",
                    *PUSH(32),
                    *PUSH(MemoryPositions.FREE_VAR_SPACE),
                    "SHA3",
                ]
            )
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
            data_node = [DataHeader(Label(code.args[0].value))]

            for c in code.args[1:]:
                if isinstance(c.value, bytes):
                    data_node.append(DATA_ITEM(c.value))
                elif isinstance(c, IRnode):
                    assert c.value == "symbol"
                    assert len(c.args) == 1
                    assert isinstance(c.args[0].value, str), (type(c.args[0].value), c)
                    data_node.append(DATA_ITEM(Label(c.args[0].value)))
                else:
                    raise ValueError(f"Invalid data: {type(c)} {c}")

            self.data_segments.append(data_node)
            return []

        # jump to a symbol, and push variable # of arguments onto stack
        if code.value == "goto":
            o = []
            for i, c in enumerate(reversed(code.args[1:])):
                o.extend(self._compile_r(c, height + i))
            o.extend([*JUMP(Label(code.args[0].value))])
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
            return [PUSHLABEL(Label(code.args[0].value))]

        # set a symbol as a location.
        if code.value == "label":
            label_name = code.args[0].value
            assert isinstance(label_name, str)

            if label_name in self.existing_labels:
                raise Exception(f"Label with name {label_name} already exists!")
            else:
                self.existing_labels.add(label_name)

            if code.args[1].value != "var_list":
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

            if symbol in self.existing_labels:
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

    def _assert_false(self):
        if self.global_revert_label is None:
            self.global_revert_label = self.mksymbol("revert")
        # use a shared failure block for common case of assert(x).
        return JUMPI(self.global_revert_label)


##############################
# assembly to evm utils
##############################


def getpos(node):
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


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
            # find the next jumpdest or sublist
            for j in range(i + 1, len(assembly)):
                next_is_jumpdest = j < len(assembly) and is_symbol(assembly[j])
                if next_is_jumpdest:
                    break
            else:
                # fixup an off-by-one if we made it to the end of the assembly
                # without finding an jumpdest or sublist
                j = len(assembly)
            changed = j > i + 1
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
            and is_symbol(assembly[i + 2])
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
        # if is_symbol(assembly[i]) and assembly[i + 1] == "JUMPDEST":
        if is_symbol(assembly[i]):
            current_symbol = assembly[i]
            if is_symbol(assembly[i + 1]):
                # LABEL x LABEL y
                # replace all instances of PUSHLABEL x with PUSHLABEL y
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

    used_jumpdests = OrderedSet()

    # find all used jumpdests
    for i in range(len(assembly)):
        if isinstance(assembly[i], PUSHLABEL):
            used_jumpdests.add(assembly[i].label)

    for item in assembly:
        if isinstance(item, list) and isinstance(item[0], DataHeader):
            # add symbols used in data sections as they are likely
            # used for a jumptable.
            for t in item:
                if is_symbol(t):
                    used_jumpdests.add(t)

    # delete jumpdests that aren't used
    i = 0
    while i < len(assembly):
        if is_symbol(assembly[i]) and assembly[i] not in used_jumpdests:
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


def adjust_pc_maps(pc_maps, ofst):
    assert ofst >= 0

    ret = {}
    # source breakpoints, don't need to modify
    ret["breakpoints"] = pc_maps["breakpoints"].copy()
    ret["pc_breakpoints"] = {pc + ofst for pc in pc_maps["pc_breakpoints"]}
    ret["pc_jump_map"] = {k + ofst: v for (k, v) in pc_maps["pc_jump_map"].items()}
    ret["pc_raw_ast_map"] = {k + ofst: v for (k, v) in pc_maps["pc_raw_ast_map"].items()}
    ret["error_map"] = {k + ofst: v for (k, v) in pc_maps["error_map"].items()}

    return ret


SYMBOL_SIZE = 2  # size of a PUSH instruction for a code symbol


def _data_to_evm(assembly, symbol_map):
    ret = bytearray()
    assert isinstance(assembly[0], DataHeader)
    for item in assembly[1:]:
        if is_symbol(item):
            symbol = symbol_map[item].to_bytes(SYMBOL_SIZE, "big")
            ret.extend(symbol)
        elif isinstance(item, int):
            ret.append(item)
        elif isinstance(item, bytes):
            ret.extend(item)
        else:
            raise ValueError(f"invalid data {type(item)} {item}")

    return ret


# predict what length of an assembly [data] node will be in bytecode
def _length_of_data(assembly):
    ret = 0
    assert isinstance(assembly[0], DataHeader)
    for item in assembly[1:]:
        if is_symbol(item):
            ret += SYMBOL_SIZE
        elif isinstance(item, int):
            assert 0 <= item < 256, f"invalid data byte {item}"
            ret += 1
        elif isinstance(item, bytes):
            ret += len(item)
        else:
            raise ValueError(f"invalid data {type(item)} {item}")

    return ret


@dataclass
class RuntimeHeader:
    label: Label

    def __repr__(self):
        return f"<RUNTIME {self.label}>"


@dataclass
class DataHeader:
    label: Label

    def __repr__(self):
        return f"DATA {self.label.label}"


##############################
# assembly to evm bytecode
##############################


# TODO: change API to split assembly_to_evm and assembly_to_source/symbol_maps
def assembly_to_evm(assembly, pc_ofst=0, compiler_metadata=None):
    bytecode, source_maps, _ = assembly_to_evm_with_symbol_map(
        assembly, pc_ofst=pc_ofst, compiler_metadata=compiler_metadata
    )
    return bytecode, source_maps


def assembly_to_evm_with_symbol_map(assembly, pc_ofst=0, compiler_metadata=None):
    """
    Assembles assembly into EVM

    assembly: list of asm instructions
    pc_ofst: when constructing the source map, the amount to offset all
             pcs by (no effect until we add deploy code source map)
    compiler_metadata: any compiler metadata to add. pass `None` to indicate
                       no metadata to be added (should always be `None` for
                       runtime code). the value is opaque, and will be passed
                       directly to `cbor2.dumps()`.
    """
    line_number_map = {
        "breakpoints": set(),
        "pc_breakpoints": set(),
        "pc_jump_map": {0: "-"},
        "pc_raw_ast_map": {},
        "error_map": {},
    }

    pc = 0
    symbol_map = {}

    ## resolve constants
    for item in assembly:
        if isinstance(item, CONST):
            # should this be merged into the symbol map?
            const_map[item.name] = item.value

    # go through the code, resolving symbolic locations
    # (i.e. JUMPDEST locations) to actual code locations
    for i, item in enumerate(assembly):
        note_line_num(line_number_map, pc, item)
        if item == "DEBUG":
            continue  # skip debug

        # update pc_jump_map
        if item == "JUMP":
            last = assembly[i - 1]
            if isinstance(last, PUSHLABEL) and last.label.label.startswith("internal"):
                if last.label.label.endswith("cleanup"):
                    # exit an internal function
                    line_number_map["pc_jump_map"][pc] = "o"
                else:
                    # enter an internal function
                    line_number_map["pc_jump_map"][pc] = "i"
            else:
                # everything else
                line_number_map["pc_jump_map"][pc] = "-"
        elif item in ("JUMPI", "JUMPDEST"):
            line_number_map["pc_jump_map"][pc] = "-"

        # update pc
        if is_symbol(item):
            if item in symbol_map:
                raise CompilerPanic(f"duplicate {item}")
            # Don't increment pc as the symbol itself doesn't go into code
            symbol_map[item] = pc

        if isinstance(item, PUSHLABEL):
            pc += SYMBOL_SIZE + 1  # PUSH2 highbits lowbits
        elif is_mem_sym(item):
            # PUSH<n> item
            pc += mem_ofst_size + 1
        elif is_ofst(item):
            assert is_symbol(item.label) or is_mem_sym(item.label), item.label
            assert isinstance(item.ofst, int), item
            # [PUSH_OFST, (Label foo), bar] -> PUSH2 (foo+bar)
            # [PUSH_OFST, _mem_foo, bar] -> PUSHN (foo+bar)
            if is_symbol(item.label):
                pc += SYMBOL_SIZE + 1  # PUSH2 highbits lowbits
            else:
                pc += mem_ofst_size + 1

        elif isinstance(item, DataHeader):
            symbol_map[item[0].label] = pc
            pc += _length_of_data(item)
        else:
            pc += 1

    bytecode_suffix = b""
    if compiler_metadata is not None:
        # this will hold true when we are in initcode
        assert immutables_len is not None
        immutables_len = symbol_map["immutables_len"]
        metadata = (
            compiler_metadata,
            len(runtime_code),
            data_section_lengths,
            immutables_len,
            {"vyper": version_tuple},
        )
        bytecode_suffix += cbor2.dumps(metadata)
        # append the length of the footer, *including* the length
        # of the length bytes themselves.
        suffix_len = len(bytecode_suffix) + 2
        bytecode_suffix += suffix_len.to_bytes(2, "big")

    pc += len(bytecode_suffix)

    symbol_map[Label("code_end")] = pc

    # TODO refactor into two functions, create symbol_map and assemble

    ret = bytearray()

    # now that all symbols have been resolved, generate bytecode
    # using the symbol map
    for item in assembly:
        if item in ("DEBUG",):
            continue  # skippable opcodes

        elif isinstance(item, PUSHLABEL):
            # push a symbol to stack
            label = item.label
            bytecode, _ = assembly_to_evm(PUSH_N(symbol_map[label], n=SYMBOL_SIZE))
            ret.extend(bytecode)

        elif isinstance(item, Label):
            ret.append(get_opcodes()["JUMPDEST"][0])

        elif is_mem_sym(item):
            # TODO: use something like PUSH_MEM_SYM(?) for these.
            bytecode, _ = assembly_to_evm(PUSH_N(symbol_map[item], n=mem_ofst_size))
            ret.extend(bytecode)

        elif is_ofst(item):
            # PUSH_OFST (LABEL foo) 32
            # PUSH_OFST (const foo) 32
            ofst = symbol_map[item.label] + item.ofst
            n = mem_ofst_size if is_mem_sym(item.label) else SYMBOL_SIZE
            bytecode, _ = assembly_to_evm(PUSH_N(ofst, n))
            ret.extend(bytecode)

        elif isinstance(item, int):
            ret.append(item)
        elif isinstance(item, str) and item.upper() in get_opcodes():
            ret.append(get_opcodes()[item.upper()][0])
        elif item[:4] == "PUSH":
            ret.append(PUSH_OFFSET + int(item[4:]))
        elif item[:3] == "DUP":
            ret.append(DUP_OFFSET + int(item[3:]))
        elif item[:4] == "SWAP":
            ret.append(SWAP_OFFSET + int(item[4:]))
        elif isinstance(item, DATA_ITEM):
            if isinstance(item.data, bytes):
                ret.extend(item.data)
            elif isinstance(item.data, Label):
                symbolbytes = symbol_map[item.data].to_bytes(SYMBOL_SIZE, "big")
                ret.extend(symbolbytes)
            else:
                raise CompilerPanic("Invalid data {type(item.data)}, {item.data}")
        else:  # pragma: no cover
            # unreachable
            raise ValueError(f"Weird symbol in assembly: {type(item)} {item}")

    ret.extend(bytecode_suffix)

    line_number_map["breakpoints"] = list(line_number_map["breakpoints"])
    line_number_map["pc_breakpoints"] = list(line_number_map["pc_breakpoints"])
    return bytes(ret), line_number_map, symbol_map
