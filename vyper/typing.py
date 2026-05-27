from typing import Dict, Optional, Sequence, Tuple

# Parser
ParserPosition = Tuple[int, int]

# Compiler
ContractPath = str
SourceCode = str
OutputFormats = Sequence[str]
StorageLayout = Dict

# Opcodes
OpcodeGasCost = int
OpcodeValue = Tuple[Optional[int], int, int, OpcodeGasCost]
OpcodeMap = Dict[str, OpcodeValue]
OpcodeRulesetValue = Tuple[Optional[int], int, int, int]
OpcodeRulesetMap = Dict[str, OpcodeRulesetValue]
