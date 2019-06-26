from typing import (
    Dict,
    Tuple,
)

# Parser
ClassTypes = Dict[str, str]
ParserPosition = Tuple[int, int]

# Compiler
ContractName = str
SourceCode = str

# Interfaces
InterfaceAsName = str
InterfaceImportPath = str
InterfaceImports = Dict[InterfaceAsName, InterfaceImportPath]
