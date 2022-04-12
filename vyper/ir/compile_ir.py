import copy
import functools

from vyper.codegen.ir_node import IRnode
from vyper.evm.opcodes import get_opcodes
from vyper.exceptions import CodegenPanic, CompilerPanic
from vyper.utils import MemoryPositions

PUSH_OFFSET = 0x5F
DUP_OFFSET = 0x7F
SWAP_OFFSET = 0x8F


CLAMP_OP_NAMES = {
    "uclamplt",
    "uclample",
    "clamplt",
    "clample",
    "uclampgt",
    "uclampge",
    "clampgt",
    "clampge",
}


def num_to_bytearray(x):
    o = []
    while x > 0:
        o.insert(0, x % 256)
        x //= 256
    return o


def PUSH(x):
    bs = num_to_bytearray(x)
    if len(bs) == 0:
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


def mkdebug(pc_debugger, source_pos):
    i = Instruction("DEBUG", source_pos)
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
            assert is_symbol(args[0].value)
            ir_node.value = "seq"

            _t = ["seq"]
            if "return_buffer" in label_params:
                _t.append(["pop", "pass"])

            dest = args[0].value[5:]  # `_sym_foo` -> `foo`
            more_args = ["pass" if t.value == "return_pc" else t for t in args[1:]]
            _t.append(["goto", dest] + more_args)
            ir_node.args = IRnode.from_list(_t, source_pos=ir_node.source_pos).args

    if ir_node.value == "label":
        label_params = set(t.value for t in ir_node.args[1].args)

    for t in args:
        _rewrite_return_sequences(t, label_params)


def _assert_false():
    # use a shared failure block for common case of assert(x).
    # in the future we might want to change the code
    # at _sym_revert0 to: INVALID
    return ["_sym_revert0", "JUMPI"]


def _add_postambles(asm_ops):
    to_append = []

    _revert0_string = ["_sym_revert0", "JUMPDEST", "PUSH1", 0, "DUP1", "REVERT"]

    if "_sym_revert0" in asm_ops:
        # shared failure block
        to_append.extend(_revert0_string)

    if len(to_append) > 0:
        # for some reason there might not be a STOP at the end of asm_ops.
        # (generally vyper programs will have it but raw IR might not).
        asm_ops.append("STOP")
        asm_ops.extend(to_append)

    # need to do this recursively since every sublist is basically
    # treated as its own program (there are no global labels.)
    for t in asm_ops:
        if isinstance(t, list):
            _add_postambles(t)


class Instruction(str):
    def __new__(cls, sstr, *args, **kwargs):
        return super().__new__(cls, sstr)

    def __init__(self, sstr, source_pos=None):
        self.pc_debugger = False
        if source_pos is not None:
            self.lineno, self.col_offset, self.end_lineno, self.end_col_offset = source_pos
        else:
            self.lineno, self.col_offset, self.end_lineno, self.end_col_offset = [None] * 4


def apply_line_numbers(func):
    @functools.wraps(func)
    def apply_line_no_wrapper(*args, **kwargs):
        code = args[0]
        ret = func(*args, **kwargs)
        new_ret = [
            Instruction(i, code.source_pos)
            if isinstance(i, str) and not isinstance(i, Instruction)
            else i
            for i in ret
        ]
        return new_ret

    return apply_line_no_wrapper


@apply_line_numbers
def compile_to_assembly(code, no_optimize=False):
    # don't overwrite ir since the original might need to be output, e.g. `-f ir,asm`
    code = copy.deepcopy(code)
    _rewrite_return_sequences(code)

    res = _compile_to_assembly(code)

    _add_postambles(res)
    if not no_optimize:
        _optimize_assembly(res)
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
        raise CompilerPanic(f"Incorrect type for existing_labels: {type(existing_labels)}")

    # Opcodes
    if isinstance(code.value, str) and code.value.upper() in get_opcodes():
        o = []
        for i, c in enumerate(code.args[::-1]):
            o.extend(_compile_to_assembly(c, withargs, existing_labels, break_dest, height + i))
        o.append(code.value.upper())
        return o

    # Numbers
    elif isinstance(code.value, int):
        if code.value < -(2 ** 255):
            raise Exception(f"Value too low: {code.value}")
        elif code.value >= 2 ** 256:
            raise Exception(f"Value too high: {code.value}")
        return PUSH(code.value % 2 ** 256)

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
        if len(code.args) != 5:
            raise CompilerPanic("bad number of repeat args")  # pragma: notest

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
        o.extend(
            _compile_to_assembly(
                start,
                withargs,
                existing_labels,
                break_dest,
                height,
            )
        )

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
            # assert rounds <= rounds_bound
            # TODO this runtime assertion should never fail for
            # internally generated repeats.
            # maybe drop it or jump to 0xFE
            o.extend(["DUP2", "GT", "_sym_revert0", "JUMPI"])

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
                body,
                withargs,
                existing_labels,
                (exit_dest, continue_dest, height + 2),
                height + 2,
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
            _compile_to_assembly(
                code.args[2],
                withargs,
                existing_labels,
                break_dest,
                height + 1,
            )
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
        padding = code.args[2].value
        assert isinstance(memsize, int), "non-int memsize"
        assert isinstance(padding, int), "non-int padding"

        begincode = mksymbol("runtime_begin")
        subcode = _compile_to_assembly(ir, {}, existing_labels, None, 0)

        o = []

        # COPY the code to memory for deploy
        o.extend(["_sym_subcode_size", begincode, "_mem_deploy_start", "CODECOPY"])

        # calculate the len of runtime code
        o.extend(["_sym_subcode_size"] + PUSH(padding) + ["ADD"])  # stack: len
        o.extend(["_mem_deploy_start"])  # stack: len mem_ofst
        o.extend(["RETURN"])

        # since the asm data structures are very primitive, to make sure
        # assembly_to_evm is able to calculate data offsets correctly,
        # we pass the memsize via magic opcodes to the subcode
        subcode = [f"_DEPLOY_MEM_OFST_{memsize}"] + subcode

        # append the runtime code after the ctor code
        o.extend([begincode, "BLANK"])
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
    # Assure (if false, invalid opcode)
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
    # Unsigned/signed clamp, check less-than
    elif code.value in CLAMP_OP_NAMES:
        if isinstance(code.args[0].value, int) and isinstance(code.args[1].value, int):
            # Checks for clamp errors at compile time as opposed to run time
            # TODO move these to optimizer.py
            args_0_val = code.args[0].value
            args_1_val = code.args[1].value
            is_free_of_clamp_errors = any(
                (
                    code.value in ("uclamplt", "clamplt") and 0 <= args_0_val < args_1_val,
                    code.value in ("uclample", "clample") and 0 <= args_0_val <= args_1_val,
                    code.value in ("uclampgt", "clampgt") and 0 <= args_0_val > args_1_val,
                    code.value in ("uclampge", "clampge") and 0 <= args_0_val >= args_1_val,
                )
            )
            if is_free_of_clamp_errors:
                return _compile_to_assembly(
                    code.args[0],
                    withargs,
                    existing_labels,
                    break_dest,
                    height,
                )
            else:
                raise Exception(
                    f"Invalid {code.value} with values {code.args[0]} and {code.args[1]}"
                )
        o = _compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height)
        o.extend(
            _compile_to_assembly(
                code.args[1],
                withargs,
                existing_labels,
                break_dest,
                height + 1,
            )
        )
        o.extend(["DUP2"])
        # Stack: num num bound
        if code.value == "uclamplt":
            o.extend(["LT", "ISZERO"])
        elif code.value == "clamplt":
            o.extend(["SLT", "ISZERO"])
        elif code.value == "uclample":
            o.extend(["GT"])
        elif code.value == "clample":
            o.extend(["SGT"])
        elif code.value == "uclampgt":
            o.extend(["GT", "ISZERO"])
        elif code.value == "clampgt":
            o.extend(["SGT", "ISZERO"])
        elif code.value == "uclampge":
            o.extend(["LT"])
        elif code.value == "clampge":
            o.extend(["SLT"])
        o.extend(_assert_false())
        return o
    # Signed clamp, check against upper and lower bounds
    elif code.value in ("clamp", "uclamp"):
        comp1 = "SGT" if code.value == "clamp" else "GT"
        comp2 = "SLT" if code.value == "clamp" else "LT"
        o = _compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height)
        o.extend(
            _compile_to_assembly(
                code.args[1],
                withargs,
                existing_labels,
                break_dest,
                height + 1,
            )
        )
        o.extend(["DUP1"])
        o.extend(
            _compile_to_assembly(
                code.args[2],
                withargs,
                existing_labels,
                break_dest,
                height + 3,
            )
        )
        o.extend(["SWAP1", comp1])
        o.extend(_assert_false())
        o.extend(["DUP1", "SWAP2", "SWAP1", comp2])
        o.extend(_assert_false())
        return o
    # Checks that a value is nonzero
    elif code.value == "clamp_nonzero":
        o = _compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height)
        o.extend(["DUP1", "ISZERO"])
        o.extend(_assert_false())
        return o
    # SHA3 a single value
    elif code.value == "sha3_32":
        o = _compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height)
        o.extend(
            [
                "PUSH1",
                MemoryPositions.FREE_VAR_SPACE,
                "MSTORE",
                "PUSH1",
                32,
                "PUSH1",
                MemoryPositions.FREE_VAR_SPACE,
                "SHA3",
            ]
        )
        return o
    # SHA3 a 64 byte value
    elif code.value == "sha3_64":
        o = _compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height)
        o.extend(_compile_to_assembly(code.args[1], withargs, existing_labels, break_dest, height))
        o.extend(
            [
                "PUSH1",
                MemoryPositions.FREE_VAR_SPACE2,
                "MSTORE",
                "PUSH1",
                MemoryPositions.FREE_VAR_SPACE,
                "MSTORE",
                "PUSH1",
                64,
                "PUSH1",
                MemoryPositions.FREE_VAR_SPACE,
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

    # jump to a symbol, and push variable # of arguments onto stack
    elif code.value == "goto":
        o = []
        for i, c in enumerate(reversed(code.args[1:])):
            o.extend(_compile_to_assembly(c, withargs, existing_labels, break_dest, height + i))
        o.extend(["_sym_" + str(code.args[0]), "JUMP"])
        return o
    # push a literal symbol
    elif isinstance(code.value, str) and is_symbol(code.value):
        return [code.value]
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

    elif code.value == "exit_to":
        raise CodegenPanic("exit_to not implemented yet!")

    # inject debug opcode.
    elif code.value == "debugger":
        return mkdebug(pc_debugger=False, source_pos=code.source_pos)
    # inject debug opcode.
    elif code.value == "pc_debugger":
        return mkdebug(pc_debugger=True, source_pos=code.source_pos)
    else:
        raise Exception("Weird code element: " + repr(code))


def note_line_num(line_number_map, item, pos):
    # Record line number attached to pos.
    if isinstance(item, Instruction):
        if item.lineno is not None:
            offsets = (item.lineno, item.col_offset, item.end_lineno, item.end_col_offset)
        else:
            offsets = None
        line_number_map["pc_pos_map"][pos] = offsets
    added_line_breakpoint = note_breakpoint(line_number_map, item, pos)
    return added_line_breakpoint


def note_breakpoint(line_number_map, item, pos):
    # Record line number attached to pos.
    if item == "DEBUG":
        # Is PC debugger, create PC breakpoint.
        if item.pc_debugger:
            line_number_map["pc_breakpoints"].add(pos)
        # Create line number breakpoint.
        else:
            line_number_map["breakpoints"].add(item.lineno + 1)


def _prune_unreachable_code(assembly):
    # In converting IR to assembly we sometimes end up with unreachable
    # instructions - POPing to clear the stack or STOPing execution at the
    # end of a function that has already returned or reverted. This should
    # be addressed in the IR, but for now we do a final sanity check here
    # to avoid unnecessary bytecode bloat.
    i = 0
    while i < len(assembly) - 1:
        if assembly[i] in ("JUMP", "RETURN", "REVERT", "STOP") and not (
            is_symbol(assembly[i + 1]) or assembly[i + 1] == "JUMPDEST"
        ):
            del assembly[i + 1]
        else:
            i += 1


def _prune_inefficient_jumps(assembly):
    # prune sequences `_sym_x JUMP _sym_x JUMPDEST` to `_sym_x JUMPDEST`
    i = 0
    while i < len(assembly) - 4:
        if (
            is_symbol(assembly[i])
            and assembly[i + 1] == "JUMP"
            and assembly[i] == assembly[i + 2]
            and assembly[i + 3] == "JUMPDEST"
        ):
            # delete _sym_x JUMP
            del assembly[i : i + 2]
        else:
            i += 1


def _merge_jumpdests(assembly):
    # When we have multiple JUMPDESTs in a row, or when a JUMPDEST
    # is immediately followed by another JUMP, we can skip the
    # intermediate jumps.
    # (Usually a chain of JUMPs is created by a nested block,
    # or some nested if statements.)
    i = 0
    while i < len(assembly) - 3:
        if is_symbol(assembly[i]) and assembly[i + 1] == "JUMPDEST":
            current_symbol = assembly[i]
            if is_symbol(assembly[i + 2]) and assembly[i + 3] == "JUMPDEST":
                # _sym_x JUMPDEST _sym_y JUMPDEST
                # replace all instances of _sym_x with _sym_y
                # (except for _sym_x JUMPDEST - don't want duplicate labels)
                new_symbol = assembly[i + 2]
                for j in range(len(assembly)):
                    if assembly[j] == current_symbol and i != j:
                        assembly[j] = new_symbol
            elif is_symbol(assembly[i + 2]) and assembly[i + 3] == "JUMP":
                # _sym_x JUMPDEST _sym_y JUMP
                # replace all instances of _sym_x with _sym_y
                # (except for _sym_x JUMPDEST - don't want duplicate labels)
                new_symbol = assembly[i + 2]
                for j in range(len(assembly)):
                    if assembly[j] == current_symbol and i != j:
                        assembly[j] = new_symbol

        i += 1


def _merge_iszero(assembly):
    i = 0
    while i < len(assembly) - 2:
        if assembly[i : i + 3] == ["ISZERO", "ISZERO", "ISZERO"]:
            del assembly[i : i + 2]
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
            del assembly[i : i + 2]
        else:
            i += 1


def _prune_unused_jumpdests(assembly):
    used_jumpdests = set()

    # find all used jumpdests
    for i in range(len(assembly) - 1):
        if is_symbol(assembly[i]) and assembly[i + 1] != "JUMPDEST":
            used_jumpdests.add(assembly[i])

    # delete jumpdests that aren't used
    i = 0
    while i < len(assembly) - 2:
        if is_symbol(assembly[i]) and assembly[i] not in used_jumpdests:
            del assembly[i : i + 2]
        else:
            i += 1


def _stack_peephole_opts(assembly):
    i = 0
    while i < len(assembly) - 2:
        # usually generated by with statements that return their input like
        # (with x (...x))
        if assembly[i : i + 3] == ["DUP1", "SWAP1", "POP"]:
            # DUP1 SWAP1 POP == no-op
            del assembly[i : i + 3]
            continue
        # usually generated by nested with statements that don't return like
        # (with x (with y ...))
        if assembly[i : i + 3] == ["SWAP1", "POP", "POP"]:
            # SWAP1 POP POP == POP POP
            del assembly[i]
            continue
        i += 1


# optimize assembly, in place
def _optimize_assembly(assembly):
    for x in assembly:
        if isinstance(x, list):
            _optimize_assembly(x)

    _prune_unreachable_code(assembly)
    _merge_iszero(assembly)
    _merge_jumpdests(assembly)
    _prune_inefficient_jumps(assembly)
    _prune_unused_jumpdests(assembly)
    _stack_peephole_opts(assembly)


# Assembles assembly into EVM
def assembly_to_evm(assembly, start_pos=0):
    line_number_map = {
        "breakpoints": set(),
        "pc_breakpoints": set(),
        "pc_jump_map": {0: "-"},
        "pc_pos_map": {},
    }

    posmap = {}
    runtime_code, runtime_code_start, runtime_code_end = None, None, None
    pos = start_pos

    # go through the code, resolving symbolic locations
    # (i.e. JUMPDEST locations) to actual code locations
    for i, item in enumerate(assembly):
        note_line_num(line_number_map, item, pos)
        if item == "DEBUG":
            continue  # skip debug

        if item == "JUMP":
            last = assembly[i - 1]
            if is_symbol(last) and last.startswith("_sym_internal"):
                if last.endswith("cleanup"):
                    # exit an internal function
                    line_number_map["pc_jump_map"][pos] = "o"
                else:
                    # enter an internal function
                    line_number_map["pc_jump_map"][pos] = "i"
            else:
                # everything else
                line_number_map["pc_jump_map"][pos] = "-"
        elif item in ("JUMPI", "JUMPDEST"):
            line_number_map["pc_jump_map"][pos] = "-"

        if is_symbol(item):
            if assembly[i + 1] == "JUMPDEST" or assembly[i + 1] == "BLANK":
                # Don't increment position as the symbol itself doesn't go into code
                if item in posmap:
                    raise CompilerPanic(f"duplicate jumpdest {item}")

                posmap[item] = pos - start_pos
            else:
                pos += 3  # PUSH2 highbits lowbits
        elif is_mem_sym(item):
            pos += 5  # PUSH4 item
        elif is_ofst(item):
            assert is_symbol(assembly[i + 1]) or is_mem_sym(assembly[i + 1])
            assert isinstance(assembly[i + 2], int)
            # [_OFST, _sym_foo, bar] -> PUSH2 (foo+bar)
            # [_OFST, _mem_foo, bar] -> PUSH4 (foo+bar)
            pos -= 1
        elif item == "BLANK":
            pos += 0
        elif isinstance(item, str) and item.startswith("_DEPLOY_MEM_OFST_"):
            # _DEPLOY_MEM_OFST is assembly magic which will
            # get removed during final assembly-to-bytecode
            pos += 0
        elif isinstance(item, list):
            assert runtime_code is None, "Multiple subcodes"
            runtime_code, sub_map = assembly_to_evm(item, start_pos=pos)
            assert item[0].startswith("_DEPLOY_MEM_OFST_")
            ctor_mem_size = int(item[0][len("_DEPLOY_MEM_OFST_") :])

            runtime_code_start, runtime_code_end = _runtime_code_offsets(
                ctor_mem_size, len(runtime_code)
            )
            assert runtime_code_end - runtime_code_start == len(runtime_code)
            pos += len(runtime_code)
            for key in line_number_map:
                line_number_map[key].update(sub_map[key])
        else:
            pos += 1

    code_end = pos - start_pos
    posmap["_sym_code_end"] = code_end
    posmap["_mem_deploy_start"] = runtime_code_start
    posmap["_mem_deploy_end"] = runtime_code_end
    if runtime_code is not None:
        posmap["_sym_subcode_size"] = len(runtime_code)

    o = b""

    to_skip = 0
    for i, item in enumerate(assembly):
        if to_skip > 0:
            to_skip -= 1
            continue

        if item in ("DEBUG", "BLANK"):
            continue  # skippable opcodes

        elif isinstance(item, str) and item.startswith("_DEPLOY_MEM_OFST_"):
            continue

        elif is_symbol(item):
            if assembly[i + 1] != "JUMPDEST" and assembly[i + 1] != "BLANK":
                bytecode, _ = assembly_to_evm(PUSH_N(posmap[item], n=2))
                o += bytecode

        elif is_mem_sym(item):
            bytecode, _ = assembly_to_evm(PUSH_N(posmap[item], n=4))
            o += bytecode

        elif is_ofst(item):
            # _OFST _sym_foo 32
            ofst = posmap[assembly[i + 1]] + assembly[i + 2]
            n = 4 if is_mem_sym(assembly[i + 1]) else 2
            bytecode, _ = assembly_to_evm(PUSH_N(ofst, n))
            o += bytecode
            to_skip = 2

        elif isinstance(item, int):
            o += bytes([item])
        elif isinstance(item, str) and item.upper() in get_opcodes():
            o += bytes([get_opcodes()[item.upper()][0]])
        elif item[:4] == "PUSH":
            o += bytes([PUSH_OFFSET + int(item[4:])])
        elif item[:3] == "DUP":
            o += bytes([DUP_OFFSET + int(item[3:])])
        elif item[:4] == "SWAP":
            o += bytes([SWAP_OFFSET + int(item[4:])])
        elif isinstance(item, list):
            o += runtime_code
        else:
            # Should never reach because, assembly is create in _compile_to_assembly.
            raise Exception("Weird symbol in assembly: " + str(item))  # pragma: no cover

    assert len(o) == pos - start_pos, (len(o), pos, start_pos)
    line_number_map["breakpoints"] = list(line_number_map["breakpoints"])
    line_number_map["pc_breakpoints"] = list(line_number_map["pc_breakpoints"])
    return o, line_number_map
