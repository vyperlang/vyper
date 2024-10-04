from tokenize import TokenInfo
from typing import Optional, Sequence, Union

# Parser
ForLoopAnnotations = dict[tuple[int, int], list[TokenInfo]]
ModificationOffsets = dict[tuple[int, int], str]
NativeHexLiteralLocations = list[tuple[int, int]]
ParserPosition = tuple[int, int]

# Compiler
ContractPath = str
SourceCode = str
OutputFormats = Sequence[str]
StorageLayout = dict

# Opcodes
OpcodeGasCost = Union[int, tuple]
OpcodeValue = tuple[Optional[int], int, int, OpcodeGasCost]
OpcodeMap = dict[str, OpcodeValue]
OpcodeRulesetValue = tuple[Optional[int], int, int, int]
OpcodeRulesetMap = dict[str, OpcodeRulesetValue]
