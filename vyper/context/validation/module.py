import importlib
import pkgutil
from typing import Union

import vyper.interfaces
from vyper import ast as vy_ast
from vyper.context.namespace import get_namespace
from vyper.context.types.function import ContractFunctionType
from vyper.context.types.utils import build_type_from_ann_assign
from vyper.context.validation.base import VyperNodeVisitorBase
from vyper.exceptions import (
    CompilerPanic,
    ExceptionList,
    UndeclaredDefinition,
    VariableDeclarationException,
    VyperException,
)
from vyper.typing import InterfaceDict


def add_module_namespace(vy_module: vy_ast.Module, interface_codes: InterfaceDict) -> None:

    """Analyzes a Vyper ast and adds all module-level objects to the namespace."""

    namespace = get_namespace()
    ModuleNodeVisitor(vy_module, interface_codes, namespace)


class ModuleNodeVisitor(VyperNodeVisitorBase):

    scope_name = "module"

    def __init__(
        self, module_node: vy_ast.Module, interface_codes: InterfaceDict, namespace: dict,
    ) -> None:
        self.ast = module_node
        self.interface_codes = interface_codes or {}
        self.namespace = namespace

        module_nodes = module_node.body.copy()
        while module_nodes:
            count = len(module_nodes)
            err_list = ExceptionList()
            for node in list(module_nodes):
                try:
                    self.visit(node)
                    module_nodes.remove(node)
                except VyperException as e:
                    err_list.append(e)

            # Only raise if no nodes were successfully processed. This allows module
            # level logic to parse regardless of the ordering of code elements.
            if count == len(module_nodes):
                err_list.raise_if_not_empty()

    def visit_AnnAssign(self, node):
        name = node.get("target.id")
        if name is None:
            raise VariableDeclarationException("Invalid module-level assignment", node)

        elif name == "implements":
            interface_name = node.annotation.id
            self.namespace[interface_name].validate_implements(node)

        else:
            var = build_type_from_ann_assign(node.annotation, node.value)
            if hasattr(var, "_member_of"):
                try:
                    self.namespace[var._member_of].add_member(name, var)
                except VyperException as exc:
                    raise exc.with_annotation(node) from None
            elif node.get("annotation.func.id") == "constant":
                # constants are added to the main namespace
                try:
                    self.namespace[name] = var
                except VyperException as exc:
                    raise exc.with_annotation(node) from None

            else:
                if node.value:
                    raise VariableDeclarationException(
                        "Storage variables cannot have an initial value", node.value
                    )
                # storage vars are added as members of self
                try:
                    self.namespace["self"].add_member(name, var)
                except VyperException as exc:
                    raise exc.with_annotation(node) from None

    def visit_ClassDef(self, node):
        type_ = self.namespace[node.class_type].build_pure_type_from_node(node)
        try:
            self.namespace[node.name] = type_
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_Import(self, node):
        _add_import(node, self.interface_codes, self.namespace)

    def visit_ImportFrom(self, node):
        _add_import(node, self.interface_codes, self.namespace)

    def visit_FunctionDef(self, node):
        func = ContractFunctionType.from_FunctionDef(node)
        try:
            self.namespace["self"].add_member(func.name, func)
        except VyperException as exc:
            raise exc.with_annotation(node) from None


def _add_import(
    node: Union[vy_ast.Import, vy_ast.ImportFrom], interface_codes: InterfaceDict, namespace: dict,
) -> None:
    if isinstance(node, vy_ast.Import):
        module = node.names[0].name
        name = node.names[0].asname
    else:
        module = node.module
        name = node.names[0].name

    if module == "vyper.interfaces":
        interface_codes = _get_builtin_interfaces()
    if name not in interface_codes:
        raise UndeclaredDefinition(f"Unknown interface: {name}", node)
    try:
        if interface_codes[name]["type"] == "vyper":
            interface_ast = vy_ast.parse_to_ast(interface_codes[name]["code"])
            interface_ast.name = name
            type_ = namespace["contract"].build_pure_type_from_node(interface_ast)
        elif interface_codes[name]["type"] == "json":
            type_ = namespace["contract"].build_pure_type_from_abi(
                name, interface_codes[name]["code"]
            )
        else:
            raise CompilerPanic(f"Unknown interface format: {interface_codes[name]['type']}")
        namespace[name] = type_
    except VyperException as exc:
        raise exc.with_annotation(node) from None


def _get_builtin_interfaces():
    interface_names = [i.name for i in pkgutil.iter_modules(vyper.interfaces.__path__)]
    return {
        name: {
            "type": "vyper",
            "code": importlib.import_module(f"vyper.interfaces.{name}").interface_code,
        }
        for name in interface_names
    }
