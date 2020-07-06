import importlib
import pkgutil
from typing import Optional, Union

import vyper.interfaces
from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context.namespace import get_namespace
from vyper.context.types.bases import DataLocation
from vyper.context.types.function import ContractFunction
from vyper.context.types.meta.event import Event
from vyper.context.types.utils import check_literal, get_type_from_annotation
from vyper.context.validation.base import VyperNodeVisitorBase
from vyper.context.validation.utils import validate_expected_type
from vyper.exceptions import (
    CallViolation,
    CompilerPanic,
    ExceptionList,
    InvalidLiteral,
    InvalidType,
    NamespaceCollision,
    StateAccessViolation,
    StructureException,
    UndeclaredDefinition,
    VariableDeclarationException,
    VyperException,
)
from vyper.typing import InterfaceDict


def add_module_namespace(vy_module: vy_ast.Module, interface_codes: InterfaceDict) -> None:

    """Analyzes a Vyper ast and adds all module-level objects to the namespace."""

    namespace = get_namespace()
    ModuleNodeVisitor(vy_module, interface_codes, namespace)


def _find_cyclic_call(fn_names: list, self_members: dict) -> Optional[list]:
    if fn_names[-1] not in self_members:
        return None
    internal_calls = self_members[fn_names[-1]].internal_calls
    for name in internal_calls:
        if name in fn_names:
            return fn_names + [name]
        sequence = _find_cyclic_call(fn_names + [name], self_members)
        if sequence:
            return sequence
    return None


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
                except (InvalidLiteral, InvalidType, VariableDeclarationException):
                    # these exceptions cannot be caused by another statement not yet being
                    # parsed, so we raise them immediately
                    raise
                except VyperException as e:
                    err_list.append(e)

            # Only raise if no nodes were successfully processed. This allows module
            # level logic to parse regardless of the ordering of code elements.
            if count == len(module_nodes):
                err_list.raise_if_not_empty()

        # get list of internal function calls made by each function
        call_function_names = set()
        self_members = namespace["self"].members
        for node in self.ast.get_children(vy_ast.FunctionDef):
            call_function_names.add(node.name)
            self_members[node.name].internal_calls = set(
                i.func.attr for i in node.get_descendants(vy_ast.Call, {"func.value.id": "self"})
            )
            if node.name in self_members[node.name].internal_calls:
                self_node = node.get_descendants(
                    vy_ast.Attribute, {"value.id": "self", "attr": node.name}
                )[0]
                raise CallViolation(f"Function '{node.name}' calls into itself", self_node)

        for fn_name in sorted(call_function_names):

            if fn_name not in self_members:
                # the referenced function does not exist - this is an issue, but we'll report
                # it later when parsing the function so we can give more meaningful output
                continue

            # check for circular function calls
            sequence = _find_cyclic_call([fn_name], self_members)
            if sequence is not None:
                nodes = []
                for i in range(len(sequence) - 1):
                    fn_node = self.ast.get_children(vy_ast.FunctionDef, {"name": sequence[i]})[0]
                    call_node = fn_node.get_descendants(
                        vy_ast.Attribute, {"value.id": "self", "attr": sequence[i + 1]}
                    )[0]
                    nodes.append(call_node)

                raise CallViolation("Contract contains cyclic function call", *nodes)

            # get complete list of functions that are reachable from this function
            function_set = set(i for i in self_members[fn_name].internal_calls if i in self_members)
            while True:
                expanded = set(x for i in function_set for x in self_members[i].internal_calls)
                expanded |= function_set
                if expanded == function_set:
                    break
                function_set = expanded

            self_members[fn_name].recursive_calls = function_set

    def visit_AnnAssign(self, node):
        name = node.get("target.id")
        if name is None:
            raise VariableDeclarationException("Invalid module-level assignment", node)

        if name == "implements":
            interface_name = node.annotation.id
            self.namespace[interface_name].validate_implements(node)
            return

        is_immutable, is_public = False, False
        annotation = node.annotation
        if isinstance(annotation, vy_ast.Call):
            # the annotation is a function call, e.g. `foo: constant(uint256)`
            call_name = annotation.get("func.id")
            if call_name in ("constant", "public"):
                validate_call_args(annotation, 1)
                if call_name == "constant":
                    # declaring a constant
                    is_immutable = True

                elif call_name == "public":
                    # declaring a public variable
                    is_public = True
                # remove the outer call node, to handle cases such as `public(map(..))`
                annotation = annotation.args[0]
        type_definition = get_type_from_annotation(
            annotation, DataLocation.STORAGE, is_immutable, is_public
        )

        if is_immutable:
            if not node.value:
                raise VariableDeclarationException("Constant must be declared with a value", node)
            if not check_literal(node.value):
                raise StateAccessViolation("Value must be a literal", node.value)

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

        try:
            self.namespace.validate_assignment(name)
        except NamespaceCollision as exc:
            raise exc.with_annotation(node) from None
        try:
            self.namespace["self"].add_member(name, type_definition)
        except NamespaceCollision:
            raise NamespaceCollision(f"Value '{name}' has already been declared", node) from None
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_EventDef(self, node):
        obj = Event.from_EventDef(node)
        try:
            self.namespace[node.name] = obj
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_FunctionDef(self, node):
        func = ContractFunction.from_FunctionDef(node)
        try:
            self.namespace["self"].add_member(func.name, func)
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_Import(self, node):
        if not node.alias:
            raise StructureException(
                "Import requires an accompanying `as` statement", node,
            )
        _add_import(node, node.name, node.alias, node.alias, self.interface_codes, self.namespace)

    def visit_ImportFrom(self, node):
        _add_import(
            node,
            node.module,
            node.name,
            node.alias or node.name,
            self.interface_codes,
            self.namespace,
        )

    def visit_InterfaceDef(self, node):
        obj = self.namespace["interface"].build_primitive_from_node(node)
        try:
            self.namespace[node.name] = obj
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_StructDef(self, node):
        obj = self.namespace["struct"].build_primitive_from_node(node)
        try:
            self.namespace[node.name] = obj
        except VyperException as exc:
            raise exc.with_annotation(node) from None


def _add_import(
    node: Union[vy_ast.Import, vy_ast.ImportFrom],
    module: str,
    name: str,
    alias: str,
    interface_codes: InterfaceDict,
    namespace: dict,
) -> None:
    if module == "vyper.interfaces":
        interface_codes = _get_builtin_interfaces()
    if name not in interface_codes:
        raise UndeclaredDefinition(f"Unknown interface: {name}", node)

    if interface_codes[name]["type"] == "vyper":
        interface_ast = vy_ast.parse_to_ast(interface_codes[name]["code"], contract_name=name)
        type_ = namespace["interface"].build_primitive_from_node(interface_ast)
    elif interface_codes[name]["type"] == "json":
        type_ = namespace["interface"].build_primitive_from_abi(name, interface_codes[name]["code"])
    else:
        raise CompilerPanic(f"Unknown interface format: {interface_codes[name]['type']}")

    try:
        namespace[alias] = type_
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
