from typing import Any, TypeVar

from vyper.evm.assembler.instructions import (
    CONST,
    CONSTREF,
    DATA_ITEM,
    PUSH_OFST,
    PUSHLABEL,
    AssemblyInstruction,
    DataHeader,
    Label,
    TaggedInstruction,
    calc_push_size,
)
from vyper.evm.opcodes import get_opcodes
from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet

SYMBOL_SIZE = 2  # size of a PUSH instruction for a code symbol


T = TypeVar("T")


def _add_to_symbol_map(symbol_map: dict[T, int], item: T, value: int):
    if item in symbol_map:  # pragma: nocover
        raise CompilerPanic(f"duplicate label: {item}")
    symbol_map[item] = value


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


def note_line_num(line_number_map, pc, item):
    # Record AST attached to pc
    if isinstance(item, TaggedInstruction):  # type: ignore
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
