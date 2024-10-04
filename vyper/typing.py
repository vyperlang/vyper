from tokenize import TokenInfo
from typing import Dict, Optional, List, Sequence, Tuple, Union

# Parser
ForLoopAnnotations = Dict[Tuple[int, int], List[TokenInfo]]
ModificationOffsets = Dict[Tuple[int, int], str]
NativeHexLiteralLocations = List[Tuple[int, int]]
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
