from typing import Any

from vyper.evm.assembler.instructions import (
    CONST,
    CONSTREF,
    DATA_ITEM,
    PUSH,
    PUSH_N,
    PUSH_OFST,
    PUSHLABEL,
    AssemblyInstruction,
    DataHeader,
    Label,
    is_label,
)
from vyper.evm.assembler.symbols import SYMBOL_SIZE, resolve_symbols
from vyper.evm.opcodes import get_opcodes
from vyper.exceptions import CompilerPanic

PUSH_OFFSET = 0x5F
DUP_OFFSET = 0x7F
SWAP_OFFSET = 0x8F


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
