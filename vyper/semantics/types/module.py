from functools import cached_property
from typing import Optional

from vyper import ast as vy_ast
from vyper.semantics.types.base import TYPE_T, VyperType
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.user import InterfaceT


# Datatype to store all module information.
class ModuleT(VyperType):
    def __init__(self, module: vy_ast.Module, name: Optional[str] = None):
        super().__init__()

        self._module = module

        self._id = name or module.path

        # compute the interface, note this has the side effect of checking
        # for function collisions
        self._helper = self.interface

        for f in self.functions:
            # note: this checks for collisions
            self.add_member(f.name, f._metadata["func_type"])

        for e in self.events:
            # add the type of the event so it can be used in call position
            self.add_member(e.name, TYPE_T(e._metadata["event_type"]))  # type: ignore

        for s in self.structs:
            # add the type of the struct so it can be used in call position
            self.add_member(s.name, TYPE_T(s._metadata["struct_type"]))  # type: ignore

        for export_decl in self.export_decls:
            for func_t in export_decl._metadata["exported_functions"]:
                assert isinstance(func_t, ContractFunctionT)
                self.add_member(func_t.name, func_t)

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return hash(id(self))

    def get_type_member(self, key: str, node: vy_ast.VyperNode) -> "VyperType":
        return self._helper.get_member(key, node)

    # this is a property, because the function set changes after AST expansion
    # TODO: rename to function_defs
    @property
    def functions(self):
        return self._module.get_children(vy_ast.FunctionDef)

    # TODO: rename to event_defs
    @property
    def events(self):
        return self._module.get_children(vy_ast.EventDef)

    # TODO: rename to struct_defs
    @property
    def structs(self):
        return self._module.get_children(vy_ast.StructDef)

    # TODO: .variables vs .variable_decls
    @cached_property
    def variables(self):
        # variables that this module defines, ex.
        # `x: uint256` is a private storage variable named x
        variable_decls = self._module.get_children(vy_ast.VariableDecl)
        return {s.target.id: s.target._metadata["varinfo"] for s in variable_decls}

    @property
    def export_decls(self):
        return self._module.get_children(vy_ast.ExportsDecl)

    # TODO maybe rename me to functions
    @property
    def function_types(self):
        return [f._metadata["func_type"] for f in self.functions]

    @property
    def external_functions(self):
        return [f for f in self.function_types if f.is_external]

    @property
    def internal_functions(self):
        return [f for f in self.function_types if f.is_internal]

    # functions that are exposed in the ABI of this contract
    # i.e., external functions + all exported functions
    @cached_property
    def exported_functions(self):
        ret = []

        for export_decl in self.export_decls:
            ret.extend(export_decl._metadata["exported_functions"])

        ret.extend(self.external_functions)

        return ret

    @cached_property
    def immutables(self):
        return [t for t in self.variables.values() if t.is_immutable]

    @cached_property
    def immutable_section_bytes(self):
        return sum([imm.typ.memory_bytes_required for imm in self.immutables])

    @cached_property
    def interface(self):
        return InterfaceT.from_ModuleT(self)
