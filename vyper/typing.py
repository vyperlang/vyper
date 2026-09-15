from typing import Dict, Optional, Sequence, Tuple

# Parser
ParserPosition = Tuple[int, int]

# Compiler
ContractPath = str
SourceCode = str
OutputFormats = Sequence[str]
StorageLayout = Dict

# Opcodes
# (opcode hex value, stack inputs, stack outputs, gas cost)
OpcodeValue = Tuple[Optional[int], int, int, int]
OpcodeMap = Dict[str, OpcodeValue]
