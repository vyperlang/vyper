"""
Code model for building Vyper contracts programmatically.

This module provides a fluent API for constructing Vyper contracts
with proper formatting and structure.
"""

from __future__ import annotations

import textwrap
from typing import Optional


class VarRef:
    """Reference to a variable with type and location information."""

    def __init__(self, name: str, typ: str, location: str, visibility: Optional[str] = None):
        self.name = name
        self.typ = typ
        self.location = location
        self.visibility = visibility

    def __str__(self) -> str:
        """Return the variable name for use in expressions."""
        # storage and transient vars need self prefix
        if self.location in ("storage", "transient"):
            return f"self.{self.name}"
        return self.name


class FunctionBuilder:
    """Builder for function definitions."""

    def __init__(self, signature: str, parent: CodeModel):
        self.signature = signature
        self.parent = parent
        self.decorators: list[str] = []
        self.body_code: Optional[str] = None
        self.is_internal = True  # functions are internal by default

        # parse just the name from the signature
        paren_idx = signature.find("(")
        if paren_idx == -1:
            raise ValueError(f"Invalid function signature: {signature}")
        self.name = signature[:paren_idx].strip()

    def __str__(self) -> str:
        """Return the function name for use in expressions."""
        if self.is_internal:
            return f"self.{self.name}"
        return self.name

    def external(self) -> FunctionBuilder:
        """Add @external decorator."""
        self.decorators.append("@external")
        self.is_internal = False
        return self

    def internal(self) -> FunctionBuilder:
        """Add @internal decorator."""
        self.decorators.append("@internal")
        self.is_internal = True
        return self

    def deploy(self) -> FunctionBuilder:
        """Add @deploy decorator."""
        self.decorators.append("@deploy")
        self.is_internal = False  # deploy functions are not called with self
        return self

    def view(self) -> FunctionBuilder:
        """Add @view decorator."""
        self.decorators.append("@view")
        return self

    def pure(self) -> FunctionBuilder:
        """Add @pure decorator."""
        self.decorators.append("@pure")
        return self

    def payable(self) -> FunctionBuilder:
        """Add @payable decorator."""
        self.decorators.append("@payable")
        return self

    def nonreentrant(self) -> FunctionBuilder:
        """Add @nonreentrant decorator."""
        self.decorators.append("@nonreentrant")
        return self

    def body(self, code: str) -> FunctionBuilder:
        """Set the function body."""
        # dedent the code to handle multi-line strings nicely
        self.body_code = textwrap.dedent(code).strip()
        return self

    def done(self) -> CodeModel:
        """Finish building the function and return to parent CodeModel."""
        return self.parent


class CodeModel:
    """Model for building a Vyper contract."""

    def __init__(self):
        self._storage_vars: list[str] = []
        self._transient_vars: list[str] = []
        self._constants: list[str] = []
        self._immutables: list[str] = []
        self._events: list[str] = []
        self._structs: list[str] = []
        self._flags: list[str] = []
        self._imports: list[str] = []
        self._local_vars: dict[str, VarRef] = {}
        self._function_builders: list[FunctionBuilder] = []

    def storage_var(self, declaration: str) -> VarRef:
        """Add a storage variable."""
        name, typ = self._parse_declaration(declaration)
        self._storage_vars.append(declaration)
        return VarRef(name, typ, "storage", "public")

    def transient_var(self, declaration: str) -> VarRef:
        """Add a transient storage variable."""
        name, typ = self._parse_declaration(declaration)
        self._transient_vars.append(f"{name}: transient({typ})")
        return VarRef(name, typ, "transient", "public")

    def constant(self, declaration: str) -> VarRef:
        """Add a constant."""
        # constants have format: "NAME: constant(type) = value"
        parts = declaration.split(":", 1)
        name = parts[0].strip()
        # extract type from constant(...) = value
        type_start = parts[1].find("constant(") + 9
        type_end = parts[1].find(")", type_start)
        typ = parts[1][type_start:type_end].strip()

        self._constants.append(declaration)
        return VarRef(name, typ, "constant", None)

    def immutable(self, declaration: str) -> VarRef:
        """Add an immutable variable."""
        name, typ = self._parse_declaration(declaration)
        self._immutables.append(f"{name}: immutable({typ})")
        return VarRef(name, typ, "immutable", "public")

    def local_var(self, name: str, typ: str) -> VarRef:
        """Register a local variable (used in function bodies)."""
        ref = VarRef(name, typ, "memory", None)
        self._local_vars[name] = ref
        return ref

    def event(self, definition: str) -> None:
        """Add an event definition."""
        self._events.append(f"event {definition}")

    def struct(self, definition: str) -> None:
        """Add a struct definition."""
        self._structs.append(f"struct {definition}")

    def flag(self, definition: str) -> None:
        """Add a flag (enum) definition."""
        self._flags.append(f"flag {definition}")

    def function(self, signature: str) -> FunctionBuilder:
        """Start building a function."""
        fb = FunctionBuilder(signature, self)
        self._function_builders.append(fb)
        return fb

    def build(self) -> str:
        """Build the complete contract code."""
        sections = []

        if self._imports:
            sections.append("\n".join(self._imports))

        if self._events:
            sections.append("\n".join(self._events))

        if self._structs:
            sections.append("\n".join(self._structs))

        if self._flags:
            sections.append("\n".join(self._flags))

        if self._constants:
            sections.append("\n".join(self._constants))

        if self._storage_vars:
            sections.append("\n".join(self._storage_vars))

        if self._transient_vars:
            sections.append("\n".join(self._transient_vars))

        if self._immutables:
            sections.append("\n".join(self._immutables))

        if self._function_builders:
            function_strings = []
            for fb in self._function_builders:
                lines = []
                lines.extend(fb.decorators)
                lines.append(f"def {fb.signature}:")

                if fb.body_code:
                    indented_body = "\n".join(f"    {line}" for line in fb.body_code.split("\n"))
                    lines.append(indented_body)
                else:
                    lines.append("    pass")

                function_strings.append("\n".join(lines))

            sections.append("\n\n".join(function_strings))

        return "\n\n".join(sections)

    def _parse_declaration(self, declaration: str) -> tuple[str, str]:
        """Parse a variable declaration of form 'name: type' into (name, type)."""
        parts = declaration.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid declaration format: {declaration}")

        name = parts[0].strip()
        typ = parts[1].strip()
        return name, typ
