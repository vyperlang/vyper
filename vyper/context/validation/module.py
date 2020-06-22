import importlib
import pkgutil
from typing import Union

import vyper.interfaces
from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context.namespace import get_namespace
from vyper.context.types.function import ContractFunctionType
from vyper.context.types.utils import check_literal, get_type_from_annotation
from vyper.context.validation.base import VyperNodeVisitorBase
from vyper.context.validation.utils import validate_expected_type
from vyper.exceptions import (
    CompilerPanic,
    ConstancyViolation,
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

        if name == "implements":
            interface_name = node.annotation.id
            self.namespace[interface_name].validate_implements(node)
            return

        is_constant, is_public = False, False
        annotation = node.annotation
        if isinstance(annotation, vy_ast.Call):
            # the annotation is a function call, e.g. `foo: constant(uint256)`
            call_name = annotation.get("func.id")
            if call_name in ("constant", "public"):
                validate_call_args(annotation, 1)
                if call_name == "constant":
                    # declaring a constant
                    is_constant = True

                elif call_name == "public":
                    # declaring a public variable
                    is_public = True
                # remove the outer call node, to handle cases such as `public(map(..))`
                annotation = annotation.args[0]
        type_definition = get_type_from_annotation(annotation, is_constant, is_public)

        if is_constant:
            if not node.value:
                raise VariableDeclarationException("Constant must be declared with a value", node)
            if not check_literal(node.value):
                raise ConstancyViolation("Value must be a literal", node.value)

            validate_expected_type(node.value, type_definition)
            try:
                self.namespace[name] = type_definition
            except VyperException as exc:
                raise exc.with_annotation(node) from None
            return

        if node.value:
            raise VariableDeclarationException(
                "Storage variables cannot have an initial value", node.value
            )
        member_key = getattr(type_definition, "_member_of", "self")
        try:
            self.namespace[member_key].add_member(name, type_definition)
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_ClassDef(self, node):
        type_ = self.namespace[node.class_type].build_primitive_from_node(node)
        try:
            self.namespace[node.name] = type_
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_FunctionDef(self, node):
        func = ContractFunctionType.from_FunctionDef(node)
        try:
            self.namespace["self"].add_member(func.name, func)
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_Import(self, node):
        _add_import(
            node, node.names[0].name, node.names[0].asname, self.interface_codes, self.namespace
        )

    def visit_ImportFrom(self, node):
        _add_import(node, node.module, node.names[0].name, self.interface_codes, self.namespace)


def _add_import(
    node: Union[vy_ast.Import, vy_ast.ImportFrom],
    module: str,
    name: str,
    interface_codes: InterfaceDict,
    namespace: dict,
) -> None:
    if module == "vyper.interfaces":
        interface_codes = _get_builtin_interfaces()
    if name not in interface_codes:
        raise UndeclaredDefinition(f"Unknown interface: {name}", node)
    try:
        if interface_codes[name]["type"] == "vyper":
            interface_ast = vy_ast.parse_to_ast(interface_codes[name]["code"])
            interface_ast.name = name
            type_ = namespace["contract"].build_primitive_from_node(interface_ast)
        elif interface_codes[name]["type"] == "json":
            type_ = namespace["contract"].build_primitive_from_abi(
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
