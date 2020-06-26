from typing import Dict, Optional, Sequence, Tuple, Union

# Parser
ModificationOffsets = Dict[Tuple[int, int], str]
ParserPosition = Tuple[int, int]

# Compiler
ContractPath = str
SourceCode = str
ContractCodes = Dict[ContractPath, SourceCode]
OutputFormats = Sequence[str]
OutputDict = Dict[ContractPath, OutputFormats]

# Interfaces
InterfaceAsName = str
InterfaceImportPath = str
InterfaceImports = Dict[InterfaceAsName, InterfaceImportPath]
InterfaceDict = Dict[ContractPath, InterfaceImports]

# Opcodes
OpcodeGasCost = Union[int, Tuple]
OpcodeValue = Tuple[Optional[int], int, int, OpcodeGasCost]
OpcodeMap = Dict[str, OpcodeValue]
OpcodeRulesetValue = Tuple[Optional[int], int, int, int]
OpcodeRulesetMap = Dict[str, OpcodeRulesetValue]
