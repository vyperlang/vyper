from functools import cached_property
from typing import Optional

from vyper import ast as vy_ast
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.function import MemberFunctionT
from vyper.semantics.types.primitives import AddressT
from vyper.semantics.types.user import InterfaceT


# Datatype to store all module information.
class ModuleT(VyperType):
    def __init__(self, module: vy_ast.Module, name: Optional[str] = None):
        self._module = module

        self._id = name or module.path

        # compute the interface, note this has the side effect of checking
        # for function collisions
        interface_t = self.interface

        members = {}

        for f in self.functions:
            members[f.name] = f._metadata["type"]

        super().__init__(members)

    def get_type_member(self, key: str, node: vy_ast.VyperNode) -> "VyperType":
        return self._helper.get_member(key, node)

    # add ctor semantics for modules until we define better semantics
    # for my_module(<address>).
    def _ctor_call_return(self, node):
        return self.interface._ctor_call_return(node)

    def _ctor_arg_types(self, node):
        return self.interface._ctor_arg_types(node)

    # this is a property, because the function set changes after AST expansion
    @property
    def functions(self):
        return self._module.get_children(vy_ast.FunctionDef)

    @cached_property
    def variables(self):
        # variables that this module defines, ex.
        # `x: uint256` is a private storage variable named x
        variable_decls = self._module.get_children(vy_ast.VariableDecl)
        return {s.target.id: s.target._metadata["varinfo"] for s in variable_decls}

    @cached_property
    def immutables(self):
        return [t for t in self.variables.values() if t.is_immutable]

    @cached_property
    def immutable_section_bytes(self):
        return sum([imm.typ.memory_bytes_required for imm in self.immutables])

    @cached_property
    def interface(self):
        return InterfaceT.from_Module(self._module, name=self._id)
