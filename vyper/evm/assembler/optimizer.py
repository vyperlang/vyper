from vyper.evm.assembler.constants import COMMUTATIVE_OPS
from vyper.evm.assembler.core import (
    DATA_ITEM,
    JUMPDEST,
    PUSH_OFST,
    PUSHLABEL,
    PUSHLABELJUMPDEST,
    Label,
    is_symbol,
)
from vyper.evm.assembler.symbols import CONSTREF, BaseConstOp
from vyper.exceptions import CompilerPanic

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
                next_is_reachable = isinstance(assembly[j], (JUMPDEST, Label, DATA_ITEM))
                if next_is_reachable:
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
    # prune sequences `PUSHLABELJUMPDEST x JUMP LABEL x` to `LABEL x`
    changed = False
    i = 0
    while i < len(assembly) - 2:
        if (
            isinstance(assembly[i], PUSHLABELJUMPDEST)
            and assembly[i + 1] == "JUMP"
            and isinstance(assembly[i + 2], (Label, JUMPDEST))
            and assembly[i + 2].label == assembly[i].label
        ):
            # delete PUSHLABELJUMPDEST x JUMP
            changed = True
            del assembly[i : i + 2]
        else:
            i += 1

    return changed


def _optimize_inefficient_jumps(assembly):
    # optimize sequences
    # `PUSHLABELJUMPDEST common JUMPI PUSHLABELJUMPDEST x JUMP LABEL common`
    # to `ISZERO PUSHLABELJUMPDEST x JUMPI LABEL common`
    changed = False
    i = 0
    while i < len(assembly) - 4:
        if (
            isinstance(assembly[i], PUSHLABELJUMPDEST)
            and assembly[i + 1] == "JUMPI"
            and isinstance(assembly[i + 2], PUSHLABELJUMPDEST)
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

    # First, identify labels that are used as data references
    data_labels = set()
    for item in assembly:
        if isinstance(item, DATA_ITEM) and isinstance(item.data, Label):
            data_labels.add(item.data)
        elif isinstance(item, PUSHLABEL):
            # PUSHLABEL is used for data references
            data_labels.add(item.label)

    changed = False
    i = 0
    while i < len(assembly) - 2:
        # if is_symbol(assembly[i]) and assembly[i + 1] == "JUMPDEST":
        if is_symbol(assembly[i]):
            current_symbol = assembly[i]

            # Skip merging if current symbol is used as data
            if current_symbol in data_labels:
                i += 1
                continue

            if is_symbol(assembly[i + 1]):
                # LABEL x LABEL y
                # Only merge jump destinations, not data references
                new_symbol = assembly[i + 1]
                if new_symbol != current_symbol:
                    for j in range(len(assembly)):
                        # Only update PUSHLABELJUMPDEST references
                        if (
                            isinstance(assembly[j], PUSHLABELJUMPDEST)
                            and assembly[j].label == current_symbol
                        ):
                            assembly[j].label = new_symbol
                            changed = True
            elif isinstance(assembly[i + 1], PUSHLABELJUMPDEST) and assembly[i + 2] == "JUMP":
                # LABEL x PUSHLABELJUMPDEST y JUMP
                # replace all instances of PUSHLABELJUMPDEST x with PUSHLABELJUMPDEST y
                new_symbol = assembly[i + 1].label
                for j in range(len(assembly)):
                    if (
                        isinstance(assembly[j], PUSHLABELJUMPDEST)
                        and assembly[j].label == current_symbol
                    ):
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
            and isinstance(assembly[i + 2], PUSHLABELJUMPDEST)
            and assembly[i + 3] == "JUMPI"
        ):
            changed = True
            del assembly[i : i + 2]
        else:
            i += 1

    return changed


def _prune_unused_jumpdests(assembly):
    changed = False

    used_as_jumpdests: set[Label] = set()
    used_as_labels: set[Label] = set()

    # find all used jumpdests
    for item in assembly:
        if isinstance(item, PUSHLABEL):
            used_as_labels.add(item.label)
        elif isinstance(item, PUSHLABELJUMPDEST):
            used_as_jumpdests.add(item.label)

        if isinstance(item, DATA_ITEM) and isinstance(item.data, Label):
            # add symbols used in data sections as they are likely
            # used for a jumptable.
            used_as_jumpdests.add(item.data)
        
        # Track labels referenced through CONSTREF
        if isinstance(item, PUSH_OFST) and isinstance(item.label, CONSTREF):
            used_as_labels.add(Label(item.label.label))
        
        # Track labels in BaseConstOp operations (CONST_ADD, CONST_SUB, etc.)
        if isinstance(item, BaseConstOp):
            for operand in [item.op1, item.op2]:
                if isinstance(operand, str):
                    used_as_labels.add(Label(operand))

    # delete jumpdests that aren't used
    i = 0
    while i < len(assembly):
        if isinstance(assembly[i], JUMPDEST):
            if assembly[i].label in used_as_jumpdests:
                i += 1
            elif assembly[i].label in used_as_labels:
                changed = True
                assembly[i] = assembly[i].label
                i += 1
            else:
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
        if assembly[i] == "SWAP1" and str(assembly[i + 1]).upper() in COMMUTATIVE_OPS:
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
