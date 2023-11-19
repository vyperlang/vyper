from typing import Dict, Optional, Sequence, Tuple, Union

# Parser
ModificationOffsets = Dict[Tuple[int, int], str]
ParserPosition = Tuple[int, int]

# Compiler
ContractPath = str
SourceCode = str
OutputFormats = Sequence[str]
StorageLayout = Dict

# Opcodes
OpcodeGasCost = Union[int, Tuple]
OpcodeValue = Tuple[Optional[int], int, int, OpcodeGasCost]
OpcodeMap = Dict[str, OpcodeValue]
OpcodeRulesetValue = Tuple[Optional[int], int, int, int]
OpcodeRulesetMap = Dict[str, OpcodeRulesetValue]
