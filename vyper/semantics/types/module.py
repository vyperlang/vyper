from functools import cached_property

from vyper import ast as vy_ast
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.user import InterfaceT


# Datatype to store all module information.
class ModuleT(VyperType):
    def __init__(self, module: vy_ast.Module):
        self._module = module

        # compute the interface, note this has the side effect of checking
        # for function collisions
        interface_t = self.interface_t

        members = {"at": interface_t}

        for f in self.functions:
            members[f.name] = f._metadata["type"]

        super().__init__(members)

    def get_type_member(self, key: str, node: vy_ast.VyperNode) -> "VyperType":
        return self._helper.get_member(key, node)

    @cached_property
    def functions(self):
        return self._module.get_children(vy_ast.FunctionDef)

    @cached_property
    def variables(self):
        # variables that this module defines, ex.
        # `x: uint256` is a private storage variable named x
        variable_decls = self._module.get_children(vy_ast.VariableDecl)
        return {s.target.id: s.target._metadata["varinfo"] for s in variable_decls}

    @property
    def immutables(self):
        return [t for t in self.variables.values() if t.is_immutable]

    @cached_property
    def immutable_section_bytes(self):
        return sum([imm.typ.memory_bytes_required for imm in self.immutables])

    @cached_property
    def interface_t(self):
        return InterfaceT.from_ast(self._module)
