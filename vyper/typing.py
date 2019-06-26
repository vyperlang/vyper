from typing import (
    Dict,
    Tuple,
)

# Parser types
ClassTypes = Dict[str, str]
ParserPosition = Tuple[int, int]

# Compiler
SourceCode = str

# Interfaces
InterfaceAsName = str
InterfaceImportPath = str
InterfaceImports = Dict[InterfaceAsName, InterfaceImportPath]
