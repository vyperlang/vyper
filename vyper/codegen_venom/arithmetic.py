"""
Safe arithmetic operations with overflow/underflow checking.

Extracted from expr.py and stmt.py to eliminate duplication.
Used for binary operations and augmented assignment.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from vyper.exceptions import CompilerPanic
from vyper.semantics.types import IntegerT
from vyper.utils import unsigned_to_signed
from vyper.venom.basicblock import IRLiteral, IROperand
from vyper.venom.builder import VenomBuilder

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext

# Workstream B will populate this file with implementations
