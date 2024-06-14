import copy
import functools
import math
from dataclasses import dataclass

import cbor2

from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.evm.opcodes import get_opcodes, version_check
from vyper.exceptions import CodegenPanic, CompilerPanic
from vyper.ir.optimizer import COMMUTATIVE_OPS
from vyper.utils import MemoryPositions
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


_next_symbol = 0


def mksymbol(name=""):
    global _next_symbol
    _next_symbol += 1

    return f"_sym_{name}{_next_symbol}"


def mkdebug(pc_debugger, ast_source):
    i = Instruction("DEBUG", ast_source)
    i.pc_debugger = pc_debugger
    return [i]


def is_symbol(i):
    return isinstance(i, str) and i.startswith("_sym_")


# basically something like a symbol which gets resolved
# during assembly, but requires 4 bytes of space.
# (should only happen in deploy code)
def is_mem_sym(i):
    return isinstance(i, str) and i.startswith("_mem_")


def is_ofst(sym):
    return isinstance(sym, str) and sym == "_OFST"


def _runtime_code_offsets(ctor_mem_size, runtime_codelen):
    # we need two numbers to calculate where the runtime code
    # should be copied to in memory (and making sure we don't
    # trample immutables, which are written to during the ctor
    # code): the memory allocated for the ctor and the length
    # of the runtime code.
    # after the ctor has run but before copying runtime code to
    # memory, the layout is
    # <ctor memory variables> ... | data section
    # and after copying runtime code to memory (immediately before
    # returning the runtime code):
    # <runtime code>          ... | data section
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


def _assert_false():
    global _revert_label
    # use a shared failure block for common case of assert(x).
    # in the future we might want to change the code
    # at _sym_revert0 to: INVALID
    return [_revert_label, "JUMPI"]


def _add_postambles(asm_ops):
    to_append = []

    global _revert_label

    _revert_string = [_revert_label, "JUMPDEST", *PUSH(0), "DUP1", "REVERT"]

    if _revert_label in asm_ops:
        # shared failure block
        to_append.extend(_revert_string)

    if len(to_append) > 0:
        # insert the postambles *before* runtime code
        # so the data section of the runtime code can't bork the postambles.
        runtime = None
        if isinstance(asm_ops[-1], list) and isinstance(asm_ops[-1][0], RuntimeHeader):
            runtime = asm_ops.pop()

        # for some reason there might not be a STOP at the end of asm_ops.
        # (generally vyper programs will have it but raw IR might not).
        asm_ops.append("STOP")
        asm_ops.extend(to_append)

        if runtime:
            asm_ops.append(runtime)

    # need to do this recursively since every sublist is basically
    # treated as its own program (there are no global labels.)
    for t in asm_ops:
        if isinstance(t, list):
            _add_postambles(t)


class Instruction(str):
    def __new__(cls, sstr, *args, **kwargs):
        return super().__new__(cls, sstr)

    def __init__(self, sstr, ast_source=None, error_msg=None):
        self.error_msg = error_msg
        self.pc_debugger = False

        self.ast_source = ast_source


def apply_line_numbers(func):
    @functools.wraps(func)
    def apply_line_no_wrapper(*args, **kwargs):
        code = args[0]
        ret = func(*args, **kwargs)

        new_ret = [
            Instruction(i, code.ast_source, code.error_msg)
            if isinstance(i, str) and not isinstance(i, Instruction)
            else i
            for i in ret
        ]
        return new_ret

    return apply_line_no_wrapper


@apply_line_numbers
def compile_to_assembly(code, optimize=OptimizationLevel.GAS):
    global _revert_label
    _revert_label = mksymbol("revert")

    # don't overwrite ir since the original might need to be output, e.g. `-f ir,asm`
    code = copy.deepcopy(code)
    _rewrite_return_sequences(code)

    res = _compile_to_assembly(code)

    _add_postambles(res)

    _relocate_segments(res)

    if optimize != OptimizationLevel.NONE:
        optimize_assembly(res)
    return res


# Compiles IR to assembly
@apply_line_numbers
def _compile_to_assembly(code, withargs=None, existing_labels=None, break_dest=None, height=0):
    if withargs is None:
        withargs = {}
    if not isinstance(withargs, dict):
        raise CompilerPanic(f"Incorrect type for withargs: {type(withargs)}")

    def _data_ofst_of(sym, ofst, height_):
        # e.g. _OFST _sym_foo 32
        assert is_symbol(sym) or is_mem_sym(sym)
        if isinstance(ofst.value, int):
            # resolve at compile time using magic _OFST op
            return ["_OFST", sym, ofst.value]
        else:
            # if we can't resolve at compile time, resolve at runtime
            ofst = _compile_to_assembly(ofst, withargs, existing_labels, break_dest, height_)
            return ofst + [sym, "ADD"]

    def _height_of(witharg):
        ret = height - withargs[witharg]
        if ret > 16:
            raise Exception("With statement too deep")
        return ret

    if existing_labels is None:
        existing_labels = set()
    if not isinstance(existing_labels, set):
        raise CompilerPanic(f"must be set(), but got {type(existing_labels)}")

    # Opcodes
    if isinstance(code.value, str) and code.value.upper() in get_opcodes():
        o = []
        for i, c in enumerate(code.args[::-1]):
            o.extend(_compile_to_assembly(c, withargs, existing_labels, break_dest, height + i))
        o.append(code.value.upper())
        return o

    # Numbers
    elif isinstance(code.value, int):
        if code.value < -(2**255):
            raise Exception(f"Value too low: {code.value}")
        elif code.value >= 2**256:
            raise Exception(f"Value too high: {code.value}")
        return PUSH(code.value % 2**256)

    # Variables connected to with statements
    elif isinstance(code.value, str) and code.value in withargs:
        return ["DUP" + str(_height_of(code.value))]

    # Setting variables connected to with statements
    elif code.value == "set":
        if len(code.args) != 2 or code.args[0].value not in withargs:
            raise Exception("Set expects two arguments, the first being a stack variable")
        if height - withargs[code.args[0].value] > 16:
            raise Exception("With statement too deep")
        return _compile_to_assembly(code.args[1], withargs, existing_labels, break_dest, height) + [
            "SWAP" + str(height - withargs[code.args[0].value]),
            "POP",
        ]

    # Pass statements
    # TODO remove "dummy"; no longer needed
    elif code.value in ("pass", "dummy"):
        return []

    # "mload" from data section of the currently executing code
    elif code.value == "dload":
        loc = code.args[0]

        o = []
        # codecopy 32 bytes to FREE_VAR_SPACE, then mload from FREE_VAR_SPACE
        o.extend(PUSH(32))
        o.extend(_data_ofst_of("_sym_code_end", loc, height + 1))
        o.extend(PUSH(MemoryPositions.FREE_VAR_SPACE) + ["CODECOPY"])
        o.extend(PUSH(MemoryPositions.FREE_VAR_SPACE) + ["MLOAD"])
        return o

    # batch copy from data section of the currently executing code to memory
    # (probably should have named this dcopy but oh well)
    elif code.value == "dloadbytes":
        dst = code.args[0]
        src = code.args[1]
        len_ = code.args[2]

        o = []
        o.extend(_compile_to_assembly(len_, withargs, existing_labels, break_dest, height))
        o.extend(_data_ofst_of("_sym_code_end", src, height + 1))
        o.extend(_compile_to_assembly(dst, withargs, existing_labels, break_dest, height + 2))
        o.extend(["CODECOPY"])
        return o

    # "mload" from the data section of (to-be-deployed) runtime code
    elif code.value == "iload":
        loc = code.args[0]

        o = []
        o.extend(_data_ofst_of("_mem_deploy_end", loc, height))
        o.append("MLOAD")

        return o

    # "mstore" to the data section of (to-be-deployed) runtime code
    elif code.value == "istore":
        loc = code.args[0]
        val = code.args[1]

        o = []
        o.extend(_compile_to_assembly(val, withargs, existing_labels, break_dest, height))
        o.extend(_data_ofst_of("_mem_deploy_end", loc, height + 1))
        o.append("MSTORE")

        return o

    # batch copy from memory to the data section of runtime code
    elif code.value == "istorebytes":
        raise Exception("unimplemented")

    # If statements (2 arguments, ie. if x: y)
    elif code.value == "if" and len(code.args) == 2:
        o = []
        o.extend(_compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height))
        end_symbol = mksymbol("join")
        o.extend(["ISZERO", end_symbol, "JUMPI"])
        o.extend(_compile_to_assembly(code.args[1], withargs, existing_labels, break_dest, height))
        o.extend([end_symbol, "JUMPDEST"])
        return o
    # If statements (3 arguments, ie. if x: y, else: z)
    elif code.value == "if" and len(code.args) == 3:
        o = []
        o.extend(_compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height))
        mid_symbol = mksymbol("else")
        end_symbol = mksymbol("join")
        o.extend(["ISZERO", mid_symbol, "JUMPI"])
        o.extend(_compile_to_assembly(code.args[1], withargs, existing_labels, break_dest, height))
        o.extend([end_symbol, "JUMP", mid_symbol, "JUMPDEST"])
        o.extend(_compile_to_assembly(code.args[2], withargs, existing_labels, break_dest, height))
        o.extend([end_symbol, "JUMPDEST"])
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
    elif code.value == "repeat":
        o = []
        if len(code.args) != 5:  # pragma: nocover
            raise CompilerPanic("bad number of repeat args")

        i_name = code.args[0]
        start = code.args[1]
        rounds = code.args[2]
        rounds_bound = code.args[3]
        body = code.args[4]

        entry_dest, continue_dest, exit_dest = (
            mksymbol("loop_start"),
            mksymbol("loop_continue"),
            mksymbol("loop_exit"),
        )

        # stack: []
        o.extend(_compile_to_assembly(start, withargs, existing_labels, break_dest, height))

        o.extend(_compile_to_assembly(rounds, withargs, existing_labels, break_dest, height + 1))

        # stack: i

        # assert rounds <= round_bound
        if rounds != rounds_bound:
            # stack: i, rounds
            o.extend(
                _compile_to_assembly(
                    rounds_bound, withargs, existing_labels, break_dest, height + 2
                )
            )
            # stack: i, rounds, rounds_bound
            # assert 0 <= rounds <= rounds_bound (for rounds_bound < 2**255)
            # TODO this runtime assertion shouldn't fail for
            # internally generated repeats.
            o.extend(["DUP2", "GT"] + _assert_false())

            # stack: i, rounds
            # if (0 == rounds) { goto end_dest; }
            o.extend(["DUP1", "ISZERO", exit_dest, "JUMPI"])

        # stack: start, rounds
        if start.value != 0:
            o.extend(["DUP2", "ADD"])

        # stack: i, exit_i
        o.extend(["SWAP1"])

        if i_name.value in withargs:
            raise CompilerPanic(f"shadowed loop variable {i_name}")
        withargs[i_name.value] = height + 1

        # stack: exit_i, i
        o.extend([entry_dest, "JUMPDEST"])
        o.extend(
            _compile_to_assembly(
                body, withargs, existing_labels, (exit_dest, continue_dest, height + 2), height + 2
            )
        )

        del withargs[i_name.value]

        # clean up any stack items left by body
        o.extend(["POP"] * body.valency)

        # stack: exit_i, i
        # increment i:
        o.extend([continue_dest, "JUMPDEST", "PUSH1", 1, "ADD"])

        # stack: exit_i, i+1 (new_i)
        # if (exit_i != new_i) { goto entry_dest }
        o.extend(["DUP2", "DUP2", "XOR", entry_dest, "JUMPI"])
        o.extend([exit_dest, "JUMPDEST", "POP", "POP"])

        return o

    # Continue to the next iteration of the for loop
    elif code.value == "continue":
        if not break_dest:
            raise CompilerPanic("Invalid break")
        dest, continue_dest, break_height = break_dest
        return [continue_dest, "JUMP"]
    # Break from inside a for loop
    elif code.value == "break":
        if not break_dest:
            raise CompilerPanic("Invalid break")
        dest, continue_dest, break_height = break_dest

        n_local_vars = height - break_height
        # clean up any stack items declared in the loop body
        cleanup_local_vars = ["POP"] * n_local_vars
        return cleanup_local_vars + [dest, "JUMP"]
    # Break from inside one or more for loops prior to a return statement inside the loop
    elif code.value == "cleanup_repeat":
        if not break_dest:
            raise CompilerPanic("Invalid break")
        # clean up local vars and internal loop vars
        _, _, break_height = break_dest
        # except don't pop label params
        if "return_buffer" in withargs:
            break_height -= 1
        if "return_pc" in withargs:
            break_height -= 1
        return ["POP"] * break_height
    # With statements
    elif code.value == "with":
        o = []
        o.extend(_compile_to_assembly(code.args[1], withargs, existing_labels, break_dest, height))
        old = withargs.get(code.args[0].value, None)
        withargs[code.args[0].value] = height
        o.extend(
            _compile_to_assembly(code.args[2], withargs, existing_labels, break_dest, height + 1)
        )
        if code.args[2].valency:
            o.extend(["SWAP1", "POP"])
        else:
            o.extend(["POP"])
        if old is not None:
            withargs[code.args[0].value] = old
        else:
            del withargs[code.args[0].value]
        return o

    # runtime statement (used to deploy runtime code)
    elif code.value == "deploy":
        memsize = code.args[0].value  # used later to calculate _mem_deploy_start
        ir = code.args[1]
        immutables_len = code.args[2].value
        assert isinstance(memsize, int), "non-int memsize"
        assert isinstance(immutables_len, int), "non-int immutables_len"

        runtime_begin = mksymbol("runtime_begin")

        subcode = _compile_to_assembly(ir)

        o = []

        # COPY the code to memory for deploy
        o.extend(["_sym_subcode_size", runtime_begin, "_mem_deploy_start", "CODECOPY"])

        # calculate the len of runtime code
        o.extend(["_OFST", "_sym_subcode_size", immutables_len])  # stack: len
        o.extend(["_mem_deploy_start"])  # stack: len mem_ofst
        o.extend(["RETURN"])

        # since the asm data structures are very primitive, to make sure
        # assembly_to_evm is able to calculate data offsets correctly,
        # we pass the memsize via magic opcodes to the subcode
        subcode = [RuntimeHeader(runtime_begin, memsize, immutables_len)] + subcode

        # append the runtime code after the ctor code
        # `append(...)` call here is intentional.
        # each sublist is essentially its own program with its
        # own symbols.
        # in the later step when the "ir" block compiled to EVM,
        # symbols in subcode are resolved to position from start of
        # runtime-code (instead of position from start of bytecode).
        o.append(subcode)

        return o

    # Seq (used to piece together multiple statements)
    elif code.value == "seq":
        o = []
        for arg in code.args:
            o.extend(_compile_to_assembly(arg, withargs, existing_labels, break_dest, height))
            if arg.valency == 1 and arg != code.args[-1]:
                o.append("POP")
        return o
    # Seq without popping.
    # unreachable keyword produces INVALID opcode
    elif code.value == "assert_unreachable":
        o = _compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height)
        end_symbol = mksymbol("reachable")
        o.extend([end_symbol, "JUMPI", "INVALID", end_symbol, "JUMPDEST"])
        return o
    # Assert (if false, exit)
    elif code.value == "assert":
        o = _compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height)
        o.extend(["ISZERO"])
        o.extend(_assert_false())
        return o

    # SHA3 a single value
    elif code.value == "sha3_32":
        o = _compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height)
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
    elif code.value == "sha3_64":
        o = _compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height)
        o.extend(
            _compile_to_assembly(code.args[1], withargs, existing_labels, break_dest, height + 1)
        )
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
    elif code.value == "select":
        # b ^ ((a ^ b) * cond) where cond is 1 or 0
        # let t = a ^ b
        cond = code.args[0]
        a = code.args[1]
        b = code.args[2]

        o = []
        o.extend(_compile_to_assembly(b, withargs, existing_labels, break_dest, height))
        o.extend(_compile_to_assembly(a, withargs, existing_labels, break_dest, height + 1))
        # stack: b a
        o.extend(["DUP2", "XOR"])
        # stack: b t
        o.extend(_compile_to_assembly(cond, withargs, existing_labels, break_dest, height + 2))
        # stack: b t cond
        o.extend(["MUL", "XOR"])

        # stack: b ^ (t * cond)
        return o

    # <= operator
    elif code.value == "le":
        return _compile_to_assembly(
            IRnode.from_list(["iszero", ["gt", code.args[0], code.args[1]]]),
            withargs,
            existing_labels,
            break_dest,
            height,
        )
    # >= operator
    elif code.value == "ge":
        return _compile_to_assembly(
            IRnode.from_list(["iszero", ["lt", code.args[0], code.args[1]]]),
            withargs,
            existing_labels,
            break_dest,
            height,
        )
    # <= operator
    elif code.value == "sle":
        return _compile_to_assembly(
            IRnode.from_list(["iszero", ["sgt", code.args[0], code.args[1]]]),
            withargs,
            existing_labels,
            break_dest,
            height,
        )
    # >= operator
    elif code.value == "sge":
        return _compile_to_assembly(
            IRnode.from_list(["iszero", ["slt", code.args[0], code.args[1]]]),
            withargs,
            existing_labels,
            break_dest,
            height,
        )
    # != operator
    elif code.value == "ne":
        return _compile_to_assembly(
            IRnode.from_list(["iszero", ["eq", code.args[0], code.args[1]]]),
            withargs,
            existing_labels,
            break_dest,
            height,
        )

    # e.g. 95 -> 96, 96 -> 96, 97 -> 128
    elif code.value == "ceil32":
        # floor32(x) = x - x % 32 == x & 0b11..100000 == x & (~31)
        # ceil32(x) = floor32(x + 31) == (x + 31) & (~31)
        x = code.args[0]
        return _compile_to_assembly(
            IRnode.from_list(["and", ["add", x, 31], ["not", 31]]),
            withargs,
            existing_labels,
            break_dest,
            height,
        )

    elif code.value == "data":
        data_node = [DataHeader("_sym_" + code.args[0].value)]

        for c in code.args[1:]:
            if isinstance(c.value, int):
                assert 0 <= c < 256, f"invalid data byte {c}"
                data_node.append(c.value)
            elif isinstance(c.value, bytes):
                data_node.append(c.value)
            elif isinstance(c, IRnode):
                assert c.value == "symbol"
                data_node.extend(
                    _compile_to_assembly(c, withargs, existing_labels, break_dest, height)
                )
            else:
                raise ValueError(f"Invalid data: {type(c)} {c}")

        # intentionally return a sublist.
        return [data_node]

    # jump to a symbol, and push variable # of arguments onto stack
    elif code.value == "goto":
        o = []
        for i, c in enumerate(reversed(code.args[1:])):
            o.extend(_compile_to_assembly(c, withargs, existing_labels, break_dest, height + i))
        o.extend(["_sym_" + code.args[0].value, "JUMP"])
        return o
    elif code.value == "djump":
        o = []
        # "djump" compiles to a raw EVM jump instruction
        jump_target = code.args[0]
        o.extend(_compile_to_assembly(jump_target, withargs, existing_labels, break_dest, height))
        o.append("JUMP")
        return o
    # push a literal symbol
    elif code.value == "symbol":
        return ["_sym_" + code.args[0].value]
    # set a symbol as a location.
    elif code.value == "label":
        label_name = code.args[0].value
        assert isinstance(label_name, str)

        if label_name in existing_labels:
            raise Exception(f"Label with name {label_name} already exists!")
        else:
            existing_labels.add(label_name)

        if code.args[1].value != "var_list":
            raise CodegenPanic("2nd arg to label must be var_list")
        var_args = code.args[1].args

        body = code.args[2]

        # new scope
        height = 0
        withargs = {}

        for arg in reversed(var_args):
            assert isinstance(
                arg.value, str
            )  # already checked for higher up but only the paranoid survive
            withargs[arg.value] = height
            height += 1

        body_asm = _compile_to_assembly(
            body, withargs=withargs, existing_labels=existing_labels, height=height
        )
        # pop_scoped_vars = ["POP"] * height
        # for now, _rewrite_return_sequences forces
        # label params to be consumed implicitly
        pop_scoped_vars = []

        return ["_sym_" + label_name, "JUMPDEST"] + body_asm + pop_scoped_vars

    elif code.value == "unique_symbol":
        symbol = code.args[0].value
        assert isinstance(symbol, str)

        if symbol in existing_labels:
            raise Exception(f"symbol {symbol} already exists!")
        else:
            existing_labels.add(symbol)

        return []

    elif code.value == "exit_to":
        raise CodegenPanic("exit_to not implemented yet!")

    # inject debug opcode.
    elif code.value == "debugger":
        return mkdebug(pc_debugger=False, ast_source=code.ast_source)
    # inject debug opcode.
    elif code.value == "pc_debugger":
        return mkdebug(pc_debugger=True, ast_source=code.ast_source)
    else:  # pragma: no cover
        raise ValueError(f"Weird code element: {type(code)} {code}")


def getpos(node):
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def note_line_num(line_number_map, pc, item):
    # Record AST attached to pc
    if isinstance(item, Instruction):
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
                next_is_jumpdest = (
                    j < len(assembly) - 1
                    and is_symbol(assembly[j])
                    and assembly[j + 1] == "JUMPDEST"
                )
                next_is_list = isinstance(assembly[j], list)
                if next_is_jumpdest or next_is_list:
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
    # prune sequences `_sym_x JUMP _sym_x JUMPDEST` to `_sym_x JUMPDEST`
    changed = False
    i = 0
    while i < len(assembly) - 4:
        if (
            is_symbol(assembly[i])
            and assembly[i + 1] == "JUMP"
            and assembly[i] == assembly[i + 2]
            and assembly[i + 3] == "JUMPDEST"
        ):
            # delete _sym_x JUMP
            changed = True
            del assembly[i : i + 2]
        else:
            i += 1

    return changed


def _optimize_inefficient_jumps(assembly):
    # optimize sequences `_sym_common JUMPI _sym_x JUMP _sym_common JUMPDEST`
    # to `ISZERO _sym_x JUMPI _sym_common JUMPDEST`
    changed = False
    i = 0
    while i < len(assembly) - 6:
        if (
            is_symbol(assembly[i])
            and assembly[i + 1] == "JUMPI"
            and is_symbol(assembly[i + 2])
            and assembly[i + 3] == "JUMP"
            and assembly[i] == assembly[i + 4]
            and assembly[i + 5] == "JUMPDEST"
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
    while i < len(assembly) - 3:
        if is_symbol(assembly[i]) and assembly[i + 1] == "JUMPDEST":
            current_symbol = assembly[i]
            if is_symbol(assembly[i + 2]) and assembly[i + 3] == "JUMPDEST":
                # _sym_x JUMPDEST _sym_y JUMPDEST
                # replace all instances of _sym_x with _sym_y
                # (except for _sym_x JUMPDEST - don't want duplicate labels)
                new_symbol = assembly[i + 2]
                if new_symbol != current_symbol:
                    for j in range(len(assembly)):
                        if assembly[j] == current_symbol and i != j:
                            assembly[j] = new_symbol
                            changed = True
            elif is_symbol(assembly[i + 2]) and assembly[i + 3] == "JUMP":
                # _sym_x JUMPDEST _sym_y JUMP
                # replace all instances of _sym_x with _sym_y
                # (except for _sym_x JUMPDEST - don't want duplicate labels)
                new_symbol = assembly[i + 2]
                for j in range(len(assembly)):
                    if assembly[j] == current_symbol and i != j:
                        assembly[j] = new_symbol
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
            and is_symbol(assembly[i + 2])
            and assembly[i + 3] == "JUMPI"
        ):
            changed = True
            del assembly[i : i + 2]
        else:
            i += 1

    return changed


# a symbol _sym_x in assembly can either mean to push _sym_x to the stack,
# or it can precede a location in code which we want to add to symbol map.
# this helper function tells us if we want to add the previous instruction
# to the symbol map.
def is_symbol_map_indicator(asm_node):
    return asm_node == "JUMPDEST"


def _prune_unused_jumpdests(assembly):
    changed = False

    used_jumpdests = set()

    # find all used jumpdests
    for i in range(len(assembly) - 1):
        if is_symbol(assembly[i]) and not is_symbol_map_indicator(assembly[i + 1]):
            used_jumpdests.add(assembly[i])

    for item in assembly:
        if isinstance(item, list) and isinstance(item[0], DataHeader):
            # add symbols used in data sections as they are likely
            # used for a jumptable.
            for t in item:
                if is_symbol(t):
                    used_jumpdests.add(t)

    # delete jumpdests that aren't used
    i = 0
    while i < len(assembly) - 2:
        if is_symbol(assembly[i]) and assembly[i] not in used_jumpdests:
            changed = True
            del assembly[i : i + 2]
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
        if assembly[i] == "SWAP1" and assembly[i + 1].lower() in COMMUTATIVE_OPS:
            changed = True
            del assembly[i]
        i += 1

    return changed


# optimize assembly, in place
def optimize_assembly(assembly):
    for x in assembly:
        if isinstance(x, list) and isinstance(x[0], RuntimeHeader):
            optimize_assembly(x)

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
    label: str
    ctor_mem_size: int
    immutables_len: int

    def __repr__(self):
        return f"<RUNTIME {self.label} mem @{self.ctor_mem_size} imms @{self.immutables_len}>"


@dataclass
class DataHeader:
    label: str

    def __repr__(self):
        return f"DATA {self.label}"


def _relocate_segments(assembly):
    # relocate all data segments to the end, otherwise data could be
    # interpreted as PUSH instructions and mangle otherwise valid jumpdests
    # relocate all runtime segments to the end as well
    data_segments = []
    non_data_segments = []
    code_segments = []
    for t in assembly:
        if isinstance(t, list):
            if isinstance(t[0], DataHeader):
                data_segments.append(t)
            else:
                _relocate_segments(t)  # recurse
                assert isinstance(t[0], RuntimeHeader)
                code_segments.append(t)
        else:
            non_data_segments.append(t)
    assembly.clear()
    assembly.extend(non_data_segments)
    assembly.extend(code_segments)
    assembly.extend(data_segments)


# TODO: change API to split assembly_to_evm and assembly_to_source/symbol_maps
def assembly_to_evm(assembly, pc_ofst=0, insert_compiler_metadata=False):
    bytecode, source_maps, _ = assembly_to_evm_with_symbol_map(
        assembly, pc_ofst=pc_ofst, insert_compiler_metadata=insert_compiler_metadata
    )
    return bytecode, source_maps


def assembly_to_evm_with_symbol_map(assembly, pc_ofst=0, insert_compiler_metadata=False):
    """
    Assembles assembly into EVM

    assembly: list of asm instructions
    pc_ofst: when constructing the source map, the amount to offset all
             pcs by (no effect until we add deploy code source map)
    insert_compiler_metadata: whether to append vyper metadata to output
                            (should be true for runtime code)
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

    runtime_code, runtime_code_start, runtime_code_end = None, None, None

    # to optimize the size of deploy code - we want to use the smallest
    # PUSH instruction possible which can support all memory symbols
    # (and also works with linear pass symbol resolution)
    # to do this, we first do a single pass to compile any runtime code
    # and use that to calculate mem_ofst_size.
    mem_ofst_size, ctor_mem_size = None, None
    max_mem_ofst = 0
    for i, item in enumerate(assembly):
        if isinstance(item, list) and isinstance(item[0], RuntimeHeader):
            assert runtime_code is None, "Multiple subcodes"

            assert ctor_mem_size is None
            ctor_mem_size = item[0].ctor_mem_size

            runtime_code, runtime_map = assembly_to_evm(item[1:])

            runtime_code_start, runtime_code_end = _runtime_code_offsets(
                ctor_mem_size, len(runtime_code)
            )
            assert runtime_code_end - runtime_code_start == len(runtime_code)

        if is_ofst(item) and is_mem_sym(assembly[i + 1]):
            max_mem_ofst = max(assembly[i + 2], max_mem_ofst)

    if runtime_code_end is not None:
        mem_ofst_size = calc_mem_ofst_size(runtime_code_end + max_mem_ofst)

    data_section_lengths = []
    immutables_len = None

    # go through the code, resolving symbolic locations
    # (i.e. JUMPDEST locations) to actual code locations
    for i, item in enumerate(assembly):
        note_line_num(line_number_map, pc, item)
        if item == "DEBUG":
            continue  # skip debug

        # update pc_jump_map
        if item == "JUMP":
            last = assembly[i - 1]
            if is_symbol(last) and last.startswith("_sym_internal"):
                if last.endswith("cleanup"):
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
            if is_symbol_map_indicator(assembly[i + 1]):
                # Don't increment pc as the symbol itself doesn't go into code
                if item in symbol_map:
                    raise CompilerPanic(f"duplicate jumpdest {item}")

                symbol_map[item] = pc
            else:
                pc += SYMBOL_SIZE + 1  # PUSH2 highbits lowbits
        elif is_mem_sym(item):
            # PUSH<n> item
            pc += mem_ofst_size + 1
        elif is_ofst(item):
            assert is_symbol(assembly[i + 1]) or is_mem_sym(assembly[i + 1])
            assert isinstance(assembly[i + 2], int)
            # [_OFST, _sym_foo, bar] -> PUSH2 (foo+bar)
            # [_OFST, _mem_foo, bar] -> PUSHN (foo+bar)
            pc -= 1
        elif isinstance(item, list) and isinstance(item[0], RuntimeHeader):
            # we are in initcode
            symbol_map[item[0].label] = pc
            # add source map for all items in the runtime map
            t = adjust_pc_maps(runtime_map, pc)
            for key in line_number_map:
                line_number_map[key].update(t[key])
            immutables_len = item[0].immutables_len
            pc += len(runtime_code)
            # grab lengths of data sections from the runtime
            for t in item:
                if isinstance(t, list) and isinstance(t[0], DataHeader):
                    data_section_lengths.append(_length_of_data(t))

        elif isinstance(item, list) and isinstance(item[0], DataHeader):
            symbol_map[item[0].label] = pc
            pc += _length_of_data(item)
        else:
            pc += 1

    bytecode_suffix = b""
    if insert_compiler_metadata:
        # this will hold true when we are in initcode
        assert immutables_len is not None
        metadata = (
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

    symbol_map["_sym_code_end"] = pc
    symbol_map["_mem_deploy_start"] = runtime_code_start
    symbol_map["_mem_deploy_end"] = runtime_code_end
    if runtime_code is not None:
        symbol_map["_sym_subcode_size"] = len(runtime_code)

    # TODO refactor into two functions, create symbol_map and assemble

    ret = bytearray()

    # now that all symbols have been resolved, generate bytecode
    # using the symbol map
    to_skip = 0
    for i, item in enumerate(assembly):
        if to_skip > 0:
            to_skip -= 1
            continue

        if item in ("DEBUG",):
            continue  # skippable opcodes

        elif is_symbol(item):
            # push a symbol to stack
            if not is_symbol_map_indicator(assembly[i + 1]):
                bytecode, _ = assembly_to_evm(PUSH_N(symbol_map[item], n=SYMBOL_SIZE))
                ret.extend(bytecode)

        elif is_mem_sym(item):
            bytecode, _ = assembly_to_evm(PUSH_N(symbol_map[item], n=mem_ofst_size))
            ret.extend(bytecode)

        elif is_ofst(item):
            # _OFST _sym_foo 32
            ofst = symbol_map[assembly[i + 1]] + assembly[i + 2]
            n = mem_ofst_size if is_mem_sym(assembly[i + 1]) else SYMBOL_SIZE
            bytecode, _ = assembly_to_evm(PUSH_N(ofst, n))
            ret.extend(bytecode)
            to_skip = 2

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
        elif isinstance(item, list) and isinstance(item[0], RuntimeHeader):
            ret.extend(runtime_code)
        elif isinstance(item, list) and isinstance(item[0], DataHeader):
            ret.extend(_data_to_evm(item, symbol_map))
        else:  # pragma: no cover
            # unreachable
            raise ValueError(f"Weird symbol in assembly: {type(item)} {item}")

    ret.extend(bytecode_suffix)

    line_number_map["breakpoints"] = list(line_number_map["breakpoints"])
    line_number_map["pc_breakpoints"] = list(line_number_map["pc_breakpoints"])
    return bytes(ret), line_number_map, symbol_map
