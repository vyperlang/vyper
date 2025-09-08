
from typing import Any, TypeVar

from build.lib.vyper.ir.compile_ir import PUSH, PUSH_N
from build.lib.vyper.utils import OrderedSet
from vyper.evm.assembler.instructions import CONST, DATA_ITEM, PUSH_OFST, PUSHLABEL, AssemblyInstruction, DataHeader, TaggedInstruction, calc_push_size
from vyper.evm.assembler.symbols import CONSTREF, Label, is_label
from vyper.evm.opcodes import get_opcodes
from vyper.exceptions import CompilerPanic

PUSH_OFFSET = 0x5F
DUP_OFFSET = 0x7F
SWAP_OFFSET = 0x8F

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

# helper functions

def _compile_push_instruction(assembly: list[AssemblyInstruction]) -> bytes:
    push_mnemonic = assembly[0]
    assert isinstance(push_mnemonic, str) and push_mnemonic.startswith("PUSH")
    push_instr = PUSH_OFFSET + int(push_mnemonic[4:])
    ret = [push_instr]

    for item in assembly[1:]:
        assert isinstance(item, int)
        ret.append(item)
    return bytes(ret)

def _compile_data_item(item: DATA_ITEM, symbol_map: dict[Label, int]) -> bytes:
    if isinstance(item.data, bytes):
        return item.data
    if isinstance(item.data, Label):
        symbolbytes = symbol_map[item.data].to_bytes(SYMBOL_SIZE, "big")
        return symbolbytes

    raise CompilerPanic(f"Invalid data {type(item.data)}, {item.data}")  # pragma: nocover


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