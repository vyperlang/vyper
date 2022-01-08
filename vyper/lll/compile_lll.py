import functools

from vyper.codegen.lll_node import LLLnode
from vyper.evm.opcodes import get_opcodes
from vyper.exceptions import CompilerPanic
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


_next_symbol = 0


def mksymbol(name=""):
    global _next_symbol
    _next_symbol += 1

    return f"_sym_{name}{_next_symbol}"


def mkdebug(pc_debugger, pos):
    i = Instruction("DEBUG", pos)
    i.pc_debugger = pc_debugger
    return [i]


def is_symbol(i):
    return isinstance(i, str) and i[:5] == "_sym_"


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
        # (generally vyper programs will have it but raw LLL might not).
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

    def __init__(self, sstr, pos=None):
        self.pc_debugger = False
        if pos is not None:
            self.lineno, self.col_offset, self.end_lineno, self.end_col_offset = pos
        else:
            self.lineno, self.col_offset, self.end_lineno, self.end_col_offset = [None] * 4


def apply_line_numbers(func):
    @functools.wraps(func)
    def apply_line_no_wrapper(*args, **kwargs):
        code = args[0]
        ret = func(*args, **kwargs)
        new_ret = [
            Instruction(i, code.pos) if isinstance(i, str) and not isinstance(i, Instruction) else i
            for i in ret
        ]
        return new_ret

    return apply_line_no_wrapper


@apply_line_numbers
def compile_to_assembly(code, no_optimize=False):
    res = _compile_to_assembly(code)

    _add_postambles(res)
    if not no_optimize:
        _optimize_assembly(res)
    return res


# Compiles LLL to assembly
@apply_line_numbers
def _compile_to_assembly(code, withargs=None, existing_labels=None, break_dest=None, height=0):
    if withargs is None:
        withargs = {}
    if not isinstance(withargs, dict):
        raise CompilerPanic(f"Incorrect type for withargs: {type(withargs)}")

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
        bytez = num_to_bytearray(code.value % 2 ** 256) or [0]
        return ["PUSH" + str(len(bytez))] + bytez
    # Variables connected to with statements
    elif isinstance(code.value, str) and code.value in withargs:
        if height - withargs[code.value] > 16:
            raise Exception("With statement too deep")
        return ["DUP" + str(height - withargs[code.value])]
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
    elif code.value in ("pass", "dummy"):
        return []
    # Code length
    elif code.value == "~codelen":
        return ["_sym_codeend"]
    # Calldataload equivalent for code
    elif code.value == "codeload":
        return _compile_to_assembly(
            LLLnode.from_list(
                [
                    "seq",
                    ["codecopy", MemoryPositions.FREE_VAR_SPACE, code.args[0], 32],
                    ["mload", MemoryPositions.FREE_VAR_SPACE],
                ]
            ),
            withargs,
            existing_labels,
            break_dest,
            height,
        )
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
    # repeat(counter_location, start, rounds, body)
    # OR
    # repeat(counter_location, start, rounds, rounds_bound, body)
    # basically a do-while loop:
    # rounds = min(rounds, rounds_bound)
    # if (rounds > 0) {
    #   do {
    #     body
    #   } while (++i != start + rounds)
    # }
    elif code.value == "repeat":
        o = []
        if len(code.args) == 4:
            iptr = code.args[0]
            start = code.args[1]
            rounds = code.args[2]
            rounds_bound = None
            body = code.args[3]
        elif len(code.args) == 5:
            iptr = code.args[0]
            start = code.args[1]
            rounds = code.args[2]
            rounds_bound = code.args[3]
            body = code.args[4]
        else:
            # should not happen
            raise CompilerPanic("bad number of repeat args")

        entry_dest, continue_dest, exit_dest = (
            mksymbol("loop_start"),
            mksymbol("loop_continue"),
            mksymbol("loop_exit"),
        )

        o.extend(_compile_to_assembly(iptr, withargs, existing_labels, break_dest, height))
        # stack: iptr
        o.extend(
            _compile_to_assembly(
                start,
                withargs,
                existing_labels,
                break_dest,
                height + 1,
            )
        )

        # stack: iptr, start
        o.extend(_compile_to_assembly(rounds, withargs, existing_labels, break_dest, height + 2))
        # rounds = min(rounds, round_bound)
        if rounds_bound is not None:
            # stack: iptr, start, rounds
            o.extend(
                _compile_to_assembly(
                    rounds_bound, withargs, existing_labels, break_dest, height + 3
                )
            )
            t = mksymbol("min")
            # stack: iptr, start, rounds, rounds_bound
            o.extend(["DUP2", "DUP2", "GT", t, "JUMPI", "SWAP1", t, "JUMPDEST", "POP"])

            # stack: iptr, start, min(rounds, round_bound) aka rounds
            # if (0 == rounds) { pop; goto end_dest; }
            t = mksymbol("rounds_nonzero")
            o.extend(["DUP1", t, "JUMPI", "POP", exit_dest, "JUMP", t, "JUMPDEST"])

        # stack: iptr, start, rounds
        o.extend(["DUP2", "DUP4", "MSTORE", "ADD"])
        # stack: iptr, exit_i
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
        # stack: iptr, exit_i
        # (with i (add 1 (mload iptr)) (seq (mstore iptr i) i))
        o.extend(
            [
                continue_dest,
                "JUMPDEST",
                "DUP2",  # iptr, exit_i
                "MLOAD",  # iptr, exit_i, i
                "PUSH1",
                1,
                "ADD",  # iptr, exit_i, i+1 (new_i)
                "DUP1",  # iptr, exit_i, new_i
                "DUP4",  # iptr, exit_i, new_i, new_i, iptr
                "MSTORE",
            ]
        )

        # stack: iptr, exit_i, new_i
        # if (exit_i != new_i) { goto entry_dest }
        o.extend(["DUP2", "XOR", entry_dest, "JUMPI"])
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
        _, _, break_height = break_dest
        # clean up local vars and internal loop vars
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
    # LLL statement (used to contain code inside code)
    elif code.value == "lll":
        o = []
        begincode = mksymbol("lll_begin")
        endcode = mksymbol("lll_end")
        o.extend([endcode, "JUMP", begincode, "BLANK"])

        lll = _compile_to_assembly(code.args[1], {}, existing_labels, None, 0)

        # `append(...)` call here is intentional.
        # each sublist is essentially its own program with its
        # own symbols.
        # in the later step when the "lll" block compiled to EVM,
        # compile_to_evm has logic to resolve symbols in "lll" to
        # position from start of runtime-code (instead of position
        # from start of bytecode).
        o.append(lll)

        o.extend([endcode, "JUMPDEST", begincode, endcode, "SUB", begincode])
        o.extend(_compile_to_assembly(code.args[0], withargs, existing_labels, break_dest, height))

        # COPY the code to memory for deploy
        o.extend(["CODECOPY", begincode, endcode, "SUB"])
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
    # <= operator
    elif code.value == "le":
        return _compile_to_assembly(
            LLLnode.from_list(["iszero", ["gt", code.args[0], code.args[1]]]),
            withargs,
            existing_labels,
            break_dest,
            height,
        )
    # >= operator
    elif code.value == "ge":
        return _compile_to_assembly(
            LLLnode.from_list(["iszero", ["lt", code.args[0], code.args[1]]]),
            withargs,
            existing_labels,
            break_dest,
            height,
        )
    # <= operator
    elif code.value == "sle":
        return _compile_to_assembly(
            LLLnode.from_list(["iszero", ["sgt", code.args[0], code.args[1]]]),
            withargs,
            existing_labels,
            break_dest,
            height,
        )
    # >= operator
    elif code.value == "sge":
        return _compile_to_assembly(
            LLLnode.from_list(["iszero", ["slt", code.args[0], code.args[1]]]),
            withargs,
            existing_labels,
            break_dest,
            height,
        )
    # != operator
    elif code.value == "ne":
        return _compile_to_assembly(
            LLLnode.from_list(["iszero", ["eq", code.args[0], code.args[1]]]),
            withargs,
            existing_labels,
            break_dest,
            height,
        )
    # e.g. 95 -> 96, 96 -> 96, 97 -> 128
    elif code.value == "ceil32":
        return _compile_to_assembly(
            LLLnode.from_list(
                [
                    "with",
                    "_val",
                    code.args[0],
                    # in mod32 arithmetic, the solution to x + y == 32 is
                    # y = bitwise_not(x) & 31
                    ["add", "_val", ["and", ["not", ["sub", "_val", 1]], 31]],
                ]
            ),
            withargs,
            existing_labels,
            break_dest,
            height,
        )
    # # jump to a symbol, and push variable arguments onto stack
    elif code.value == "goto":
        o = []
        for i, c in enumerate(reversed(code.args[1:])):
            o.extend(_compile_to_assembly(c, withargs, existing_labels, break_dest, height + i))
        o.extend(["_sym_" + str(code.args[0]), "JUMP"])
        return o
    elif isinstance(code.value, str) and is_symbol(code.value):
        return [code.value]
    # set a symbol as a location.
    elif code.value == "label":
        label_name = str(code.args[0])

        if label_name in existing_labels:
            raise Exception(f"Label with name {label_name} already exists!")
        else:
            existing_labels.add(label_name)

        return ["_sym_" + label_name, "JUMPDEST"]
    # inject debug opcode.
    elif code.value == "debugger":
        return mkdebug(pc_debugger=False, pos=code.pos)
    # inject debug opcode.
    elif code.value == "pc_debugger":
        return mkdebug(pc_debugger=True, pos=code.pos)
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
    # In converting LLL to assembly we sometimes end up with unreachable
    # instructions - POPing to clear the stack or STOPing execution at the
    # end of a function that has already returned or reverted. This should
    # be addressed in the LLL, but for now we do a final sanity check here
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
    sub_assemblies = []
    codes = []
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
        elif item == "BLANK":
            pos += 0
        elif isinstance(item, list):
            c, sub_map = assembly_to_evm(item, start_pos=pos)
            sub_assemblies.append(item)
            codes.append(c)
            pos += len(c)
            for key in line_number_map:
                line_number_map[key].update(sub_map[key])
        else:
            pos += 1

    posmap["_sym_codeend"] = pos
    o = b""
    for i, item in enumerate(assembly):
        if item == "DEBUG":
            continue  # skip debug
        elif is_symbol(item):
            if assembly[i + 1] != "JUMPDEST" and assembly[i + 1] != "BLANK":
                o += bytes([PUSH_OFFSET + 2, posmap[item] // 256, posmap[item] % 256])
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
        elif item == "BLANK":
            pass
        elif isinstance(item, list):
            for j in range(len(sub_assemblies)):
                if sub_assemblies[j] == item:
                    o += codes[j]
                    break
        else:
            # Should never reach because, assembly is create in _compile_to_assembly.
            raise Exception("Weird symbol in assembly: " + str(item))  # pragma: no cover

    assert len(o) == pos - start_pos
    line_number_map["breakpoints"] = list(line_number_map["breakpoints"])
    line_number_map["pc_breakpoints"] = list(line_number_map["pc_breakpoints"])
    return o, line_number_map
