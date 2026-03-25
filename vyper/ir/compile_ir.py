from __future__ import annotations

import contextlib
import copy
from typing import Any, Optional

import cbor2

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.evm.assembler.core import assembly_to_evm, get_data_segment_lengths
from vyper.evm.assembler.instructions import (
    CONST,
    DATA_ITEM,
    JUMP,
    JUMPI,
    PUSH,
    PUSH_OFST,
    PUSHLABEL,
    AssemblyInstruction,
    DataHeader,
    TaggedInstruction,
    mkdebug,
)
from vyper.evm.assembler.optimizer import optimize_assembly
from vyper.evm.assembler.symbols import CONSTREF, Label
from vyper.evm.opcodes import get_opcodes
from vyper.exceptions import CodegenPanic, CompilerPanic
from vyper.utils import MemoryPositions
from vyper.version import version_tuple


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
