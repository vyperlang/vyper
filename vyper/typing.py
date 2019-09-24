from typing import (
    Dict,
    Sequence,
    Tuple,
)

# Parser
ClassTypes = Dict[str, str]
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
