import importlib
import pkgutil
from typing import Optional, Union

import vyper.builtins.interfaces
from vyper import ast as vy_ast
from vyper.evm.opcodes import version_check
from vyper.exceptions import (
    CallViolation,
    CompilerPanic,
    ExceptionList,
    InvalidLiteral,
    InvalidType,
    NamespaceCollision,
    StateAccessViolation,
    StructureException,
    SyntaxException,
    UndeclaredDefinition,
    VariableDeclarationException,
    VyperException,
)
from vyper.semantics.analysis.base import VarInfo
from vyper.semantics.analysis.common import VyperNodeVisitorBase
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.analysis.utils import (
    check_constant,
    validate_expected_type,
    validate_unique_method_ids,
)
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.namespace import Namespace, get_namespace
from vyper.semantics.types import EnumT, EventT, InterfaceT, StructT
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.utils import type_from_annotation
from vyper.typing import InterfaceDict


def add_module_namespace(vy_module: vy_ast.Module, interface_codes: InterfaceDict) -> None:
    """
    Analyze a Vyper module AST node, add all module-level objects to the
    namespace and validate top-level correctness
    """

    namespace = get_namespace()
    ModuleAnalyzer(vy_module, interface_codes, namespace)


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


class ModuleAnalyzer(VyperNodeVisitorBase):
    scope_name = "module"

    def __init__(
        self, module_node: vy_ast.Module, interface_codes: InterfaceDict, namespace: Namespace
    ) -> None:
        self.ast = module_node
        self.interface_codes = interface_codes or {}
        self.namespace = namespace

        # TODO: Move computation out of constructor
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

        # generate an `InterfaceT` from the top-level node - used for building the ABI
        interface = InterfaceT.from_ast(module_node)
        module_node._metadata["type"] = interface
        self.interface = interface  # this is useful downstream

        # attach namespace to the module for downstream use.
        _ns = Namespace()
        # note that we don't just copy the namespace because
        # there are constructor issues.
        _ns.update({k: namespace[k] for k in namespace._scopes[-1]})
        module_node._metadata["namespace"] = _ns

        # check for collisions between 4byte function selectors
        # internal functions are intentionally included in this check, to prevent breaking
        # changes in in case of a future change to their calling convention
        self_members = namespace["self"].typ.members
        functions = [i for i in self_members.values() if isinstance(i, ContractFunctionT)]
        validate_unique_method_ids(functions)

        # get list of internal function calls made by each function
        function_defs = self.ast.get_children(vy_ast.FunctionDef)
        function_names = set(node.name for node in function_defs)
        for node in function_defs:
            calls_to_self = set(
                i.func.attr for i in node.get_descendants(vy_ast.Call, {"func.value.id": "self"})
            )
            # anything that is not a function call will get semantically checked later
            calls_to_self = calls_to_self.intersection(function_names)
            self_members[node.name].internal_calls = calls_to_self

        for fn_name in sorted(function_names):
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

    def visit_ImplementsDecl(self, node):
        type_ = type_from_annotation(node.annotation)
        if not isinstance(type_, InterfaceT):
            raise StructureException("Invalid interface name", node.annotation)

        type_.validate_implements(node)

    def visit_VariableDecl(self, node):
        name = node.get("target.id")
        if name is None:
            raise VariableDeclarationException("Invalid module-level assignment", node)

        if node.is_public:
            # generate function type and add to metadata
            # we need this when building the public getter
            node._metadata["func_type"] = ContractFunctionT.getter_from_VariableDecl(node)

        if node.is_immutable:
            # mutability is checked automatically preventing assignment
            # outside of the constructor, here we just check a value is assigned,
            # not necessarily where
            assignments = self.ast.get_descendants(
                vy_ast.Assign, filters={"target.id": node.target.id}
            )
            if not assignments:
                # Special error message for common wrong usages via `self.<immutable name>`
                wrong_self_attribute = self.ast.get_descendants(
                    vy_ast.Attribute, {"value.id": "self", "attr": node.target.id}
                )
                message = (
                    "Immutable variables must be accessed without 'self'"
                    if len(wrong_self_attribute) > 0
                    else "Immutable definition requires an assignment in the constructor"
                )
                raise SyntaxException(message, node.node_source_code, node.lineno, node.col_offset)

        data_loc = (
            DataLocation.CODE
            if node.is_immutable
            else DataLocation.UNSET
            if node.is_constant
            # XXX: needed if we want separate transient allocator
            # else DataLocation.TRANSIENT
            # if node.is_transient
            else DataLocation.STORAGE
        )

        type_ = type_from_annotation(node.annotation, data_loc)

        if node.is_transient and not version_check(begin="cancun"):
            raise StructureException("`transient` is not available pre-cancun", node.annotation)

        var_info = VarInfo(
            type_,
            decl_node=node,
            location=data_loc,
            is_constant=node.is_constant,
            is_public=node.is_public,
            is_immutable=node.is_immutable,
            is_transient=node.is_transient,
        )
        node.target._metadata["varinfo"] = var_info  # TODO maybe put this in the global namespace
        node._metadata["type"] = type_

        def _finalize():
            # add the variable name to `self` namespace if the variable is either
            # 1. a public constant or immutable; or
            # 2. a storage variable, whether private or public
            if (node.is_constant or node.is_immutable) and not node.is_public:
                return

            try:
                self.namespace["self"].typ.add_member(name, var_info)
                node.target._metadata["type"] = type_
            except NamespaceCollision:
                raise NamespaceCollision(
                    f"Value '{name}' has already been declared", node
                ) from None
            except VyperException as exc:
                raise exc.with_annotation(node) from None

        def _validate_self_namespace():
            # block globals if storage variable already exists
            try:
                if name in self.namespace["self"].typ.members:
                    raise NamespaceCollision(
                        f"Value '{name}' has already been declared", node
                    ) from None
                self.namespace[name] = var_info
            except VyperException as exc:
                raise exc.with_annotation(node) from None

        if node.is_constant:
            if not node.value:
                raise VariableDeclarationException("Constant must be declared with a value", node)
            if not check_constant(node.value):
                raise StateAccessViolation("Value must be a literal", node.value)

            validate_expected_type(node.value, type_)
            _validate_self_namespace()

            return _finalize()

        if node.value:
            var_type = "Immutable" if node.is_immutable else "Storage"
            raise VariableDeclarationException(
                f"{var_type} variables cannot have an initial value", node.value
            )

        if node.is_immutable:
            _validate_self_namespace()
            return _finalize()

        try:
            self.namespace.validate_assignment(name)
        except NamespaceCollision as exc:
            raise exc.with_annotation(node) from None

        return _finalize()

    def visit_EnumDef(self, node):
        obj = EnumT.from_EnumDef(node)
        try:
            self.namespace[node.name] = obj
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_EventDef(self, node):
        obj = EventT.from_EventDef(node)
        try:
            self.namespace[node.name] = obj
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_FunctionDef(self, node):
        func = ContractFunctionT.from_FunctionDef(node)

        try:
            self.namespace["self"].typ.add_member(func.name, func)
            node._metadata["type"] = func
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_Import(self, node):
        if not node.alias:
            raise StructureException("Import requires an accompanying `as` statement", node)
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
        obj = InterfaceT.from_ast(node)
        try:
            self.namespace[node.name] = obj
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_StructDef(self, node):
        struct_t = StructT.from_ast_def(node)
        try:
            self.namespace[node.name] = struct_t
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
        suggestions_str = get_levenshtein_error_suggestions(name, _get_builtin_interfaces(), 1.0)
        raise UndeclaredDefinition(f"Unknown interface: {name}. {suggestions_str}", node)

    if interface_codes[name]["type"] == "vyper":
        interface_ast = vy_ast.parse_to_ast(interface_codes[name]["code"], contract_name=name)
        type_ = InterfaceT.from_ast(interface_ast)
    elif interface_codes[name]["type"] == "json":
        type_ = InterfaceT.from_json_abi(name, interface_codes[name]["code"])  # type: ignore
    else:
        raise CompilerPanic(f"Unknown interface format: {interface_codes[name]['type']}")

    try:
        namespace[alias] = type_
    except VyperException as exc:
        raise exc.with_annotation(node) from None


def _get_builtin_interfaces():
    interface_names = [i.name for i in pkgutil.iter_modules(vyper.builtins.interfaces.__path__)]
    return {
        name: {
            "type": "vyper",
            "code": importlib.import_module(f"vyper.builtins.interfaces.{name}").interface_code,
        }
        for name in interface_names
    }
