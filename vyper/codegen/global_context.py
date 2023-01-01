from functools import cached_property
from typing import Optional

from vyper import ast as vy_ast
from vyper.codegen.context import VariableRecord
from vyper.exceptions import CompilerPanic, InvalidType, StructureException
from vyper.semantics.namespace import get_namespace, override_global_namespace
from vyper.semantics.types import EnumT
from vyper.semantics.types.utils import type_from_annotation
from vyper.typing import InterfaceImports


# Datatype to store all global context information.
# TODO: rename me to ModuleT
class GlobalContext:
    def __init__(self):
        self._contracts = dict()
        self._interfaces = dict()
        self._interface = dict()

        self._enums = dict()
        self._globals = dict()
        self._function_defs = list()

        self._module = None  # mypy hint

    @cached_property
    def variables(self):
        # variables that this module defines, ex.
        # `x: uint256` is a private storage variable named x
        variable_decls = self._module.get_children(vy_ast.VariableDecl)
        return {s.target.id: s.target._metadata["varinfo"] for s in variable_decls}

    # Parse top-level functions and variables
    @classmethod
    # TODO rename me to `from_module`
    def get_global_context(
        cls, vyper_module: "vy_ast.Module", interface_codes: Optional[InterfaceImports] = None
    ) -> "GlobalContext":
        # TODO is this a cyclic import?
        from vyper.ast.signatures.interface import extract_sigs, get_builtin_interfaces

        interface_codes = {} if interface_codes is None else interface_codes
        global_ctx = cls()

        global_ctx._module = vyper_module

        for item in vyper_module:
            if isinstance(item, vy_ast.InterfaceDef):
                global_ctx._contracts[item.name] = GlobalContext.make_contract(item)

            elif isinstance(item, vy_ast.EnumDef):
                global_ctx._enums[item.name] = EnumT.from_EnumDef(item)

            # Function definitions
            elif isinstance(item, vy_ast.FunctionDef):
                global_ctx._function_defs.append(item)
            elif isinstance(item, vy_ast.ImportFrom):
                interface_name = item.name
                assigned_name = item.alias or item.name
                if assigned_name in global_ctx._interfaces:
                    raise StructureException(f"Duplicate import of {interface_name}", item)

                if not item.level and item.module == "vyper.interfaces":
                    built_in_interfaces = get_builtin_interfaces()
                    if interface_name not in built_in_interfaces:
                        raise StructureException(
                            f"Built-In interface {interface_name} does not exist.", item
                        )
                    global_ctx._interfaces[assigned_name] = built_in_interfaces[
                        interface_name
                    ].copy()
                else:
                    if interface_name not in interface_codes:
                        raise StructureException(f"Unknown interface {interface_name}", item)
                    global_ctx._interfaces[assigned_name] = extract_sigs(
                        interface_codes[interface_name], interface_name
                    )
            elif isinstance(item, vy_ast.Import):
                interface_name = item.alias
                if interface_name in global_ctx._interfaces:
                    raise StructureException(f"Duplicate import of {interface_name}", item)
                if interface_name not in interface_codes:
                    raise StructureException(f"Unknown interface {interface_name}", item)
                global_ctx._interfaces[interface_name] = extract_sigs(
                    interface_codes[interface_name], interface_name
                )

        return global_ctx

    # A contract is a list of functions.
    @staticmethod
    def make_contract(node: "vy_ast.InterfaceDef") -> list:
        _defs = []
        for item in node.body:
            # Function definitions
            if isinstance(item, vy_ast.FunctionDef):
                _defs.append(item)
            else:
                raise StructureException("Invalid contract reference", item)
        return _defs

    @property
    def interface_names(self):
        """
        The set of names which are known to possibly be InterfaceType
        """
        return set(self._contracts.keys()) | set(self._interfaces.keys())

    def parse_type(self, ast_node):
        # kludge implementation for backwards compatibility.
        # TODO: replace with type_from_ast
        try:
            ns = self._module._metadata["namespace"]
        except AttributeError:
            ns = get_namespace()
        with override_global_namespace(ns):
            return type_from_annotation(ast_node)

    @property
    def immutables(self):
        return [t for t in self.variables.values() if t.is_immutable]

    @cached_property
    def immutable_section_bytes(self):
        return sum([imm.typ.memory_bytes_required for imm in self.immutables])
