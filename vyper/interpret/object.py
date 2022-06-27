from typing import Any
from vyper.codegen.types.types import BaseType
from dataclasses import dataclass

@dataclass
class VyperObject:
    value: Any
    typ: BaseType
