import importlib
import pkgutil

from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.context.definitions import (
    ContractFunction,
    Literal,
    get_variable_from_nodes,
)
from vyper.context.utils import (
    VyperNodeVisitorBase,
)
from vyper.exceptions import (
    CompilerPanic,
    ExceptionList,
    UndeclaredDefinition,
    VariableDeclarationException,
    VyperException,
)
import vyper.interfaces


def add_module_namespace(vy_module: vy_ast.Module, interface_codes):

    """Analyzes a Vyper ast and adds all module-level objects to the namespace."""

    ModuleNodeVisitor(vy_module, interface_codes)


class ModuleNodeVisitor(VyperNodeVisitorBase):

    scope_name = "module"

    def __init__(self, module_node, interface_codes):
        self.interface_codes = interface_codes or {}
        self.ast = module_node

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
        name = node.get('target.id')
        if name is None:
            raise VariableDeclarationException("Invalid module-level assignment", node)

        elif name == "implements":
            interface_name = node.annotation.id
            namespace[interface_name].validate_implements(node)

        else:
            var = get_variable_from_nodes(name, node.annotation, node.value)
            if hasattr(var, '_member_of'):
                try:
                    namespace[var._member_of].add_member(name, var)
                except VyperException as exc:
                    raise exc.with_annotation(node)
            elif isinstance(var, Literal):
                # constants are added to the main namespace
                try:
                    namespace[name] = var
                except VyperException as exc:
                    raise exc.with_annotation(node)

                if isinstance(node.value, (vy_ast.Constant, vy_ast.List)):
                    vy_ast.folding.replace_constant(self.ast, name, node.value)
                    # TODO delete the assignment?
            else:
                if node.value:
                    raise VariableDeclarationException(
                        "Storage variables cannot have an initial value", node.value
                    )
                # storage vars are added as members of self
                try:
                    namespace["self"].add_member(name, var)
                except VyperException as exc:
                    raise exc.with_annotation(node)

    def visit_ClassDef(self, node):
        try:
            namespace[node.name] = namespace[node.class_type].get_type(node)
        except VyperException as exc:
            raise exc.with_annotation(node)

    def visit_Import(self, node):
        _add_import(node, self.interface_codes)

    def visit_ImportFrom(self, node):
        _add_import(node, self.interface_codes)

    def visit_FunctionDef(self, node):
        func = ContractFunction.from_FunctionDef(node)
        try:
            namespace["self"].add_member(func.name, func)
        except VyperException as exc:
            raise exc.with_annotation(node)


def _add_import(node, interface_codes):
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
    if interface_codes[name]['type'] == "vyper":
        interface_ast = vy_ast.parse_to_ast(interface_codes[name]['code'])
        interface_ast.name = name
        namespace[name] = namespace['contract'].get_type(interface_ast)
    elif interface_codes[name]['type'] == "json":
        obj = namespace['contract'].get_type_from_abi(name, interface_codes[name]['code'])
        namespace[name] = obj
    else:
        raise CompilerPanic(f"Unknown interface format: {interface_codes[name]['type']}")


def _get_builtin_interfaces():
    interface_names = [i.name for i in pkgutil.iter_modules(vyper.interfaces.__path__)]
    return {
        name: {
            'type': 'vyper',
            'code': importlib.import_module(f'vyper.interfaces.{name}').interface_code,
        } for name in interface_names
    }
