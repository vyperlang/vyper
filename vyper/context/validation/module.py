from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.context.definitions import (
    get_event_from_node,
    get_function_from_node,
    get_variable_from_nodes,
)
from vyper.context.types.units import (
    Unit,
)
from vyper.context.utils import (
    VyperNodeVisitorBase,
)
from vyper.exceptions import (
    ParserException,
    StructureException,
    VariableDeclarationException,
)


def add_module_namespace(vy_module: vy_ast.Module, interface_codes):

    """Analyzes a Vyper ast and adds all module-level objects to the namespace."""

    ModuleNodeVisitor(vy_module, interface_codes)


class ModuleNodeVisitor(VyperNodeVisitorBase):

    scope_name = "module"

    def __init__(self, module_node, interface_codes):
        self.interface_codes = interface_codes
        self.units_added = False
        module_nodes = module_node.body.copy()
        while module_nodes:
            count = len(module_nodes)
            err_msg = []
            for node in list(module_nodes):
                try:
                    self.visit(node)
                    module_nodes.remove(node)
                except ParserException as e:
                    err_msg.append(f"{type(e).__name__}: {e}")
            if count == len(module_nodes):
                raise StructureException(
                    "Compilation failed with the following errors:\n\n" +
                    "\n\n".join(err_msg)
                )

    def visit_AnnAssign(self, node):
        if node.get('annotation.func.id') == "event":
            event = get_event_from_node(node)
            namespace["log"].add_member(node.target.id, event)
            return

        name = node.get('target.id')
        if name is None:
            raise VariableDeclarationException("Invalid module-level assignment", node)

        if name == "units":
            if self.units_added:
                raise VariableDeclarationException("Custom units can only be defined once", node)
            _add_custom_units(node)

        elif name == "implements":
            interface_name = node.annotation.id
            namespace[interface_name].validate_implements(node)

        else:
            var = get_variable_from_nodes(name, node.annotation, node.value)
            if not var.is_constant and node.value:
                raise VariableDeclarationException(
                    "Storage variables cannot have an initial value", node.value
                )

            if var.is_constant:
                # constants are added to the main namespace
                namespace[name] = var
            else:
                # storage vars are added as members of self
                namespace["self"].add_member(name, var)

    def visit_ClassDef(self, node):
        namespace[node.name] = namespace[node.class_type].get_type(node)

    def visit_Import(self, node):
        _add_import(node, self.interface_codes)

    def visit_ImportFrom(self, node):
        _add_import(node, self.interface_codes)

    def visit_FunctionDef(self, node):
        func = get_function_from_node(node)
        namespace["self"].add_member(func.name, func)


def _add_custom_units(node):
    # extracts custom unit information from AST
    # verifies correctness of custom units and that they are declared at most once

    for key, value in zip(node.annotation.keys, node.annotation.values):
        if not isinstance(value, vy_ast.Str):
            raise VariableDeclarationException(
                "Custom unit description must be a valid string", value
            )
        if not isinstance(key, vy_ast.Name):
            raise VariableDeclarationException(
                "Custom unit name must be a valid string", key
            )
        namespace[key.id] = Unit(name=key.id, description=value.s)


def _add_import(node, interface_codes):
    if isinstance(node, vy_ast.Import):
        name = node.names[0].asname
    else:
        name = node.names[0].name

    if name not in interface_codes:
        raise StructureException(f"Unknown interface: {name}", node)
    if interface_codes[name]['type'] == "vyper":
        interface_ast = vy_ast.parse_to_ast(interface_codes[name]['code'])
        interface_ast.name = name
        namespace[name] = namespace['contract'].get_type(interface_ast)
    elif interface_codes[name]['type'] == "json":
        obj = namespace['contract'].get_type_from_abi(name, interface_codes[name]['code'])
        namespace[name] = obj
    else:
        raise StructureException(
            f"Unknown interface format: {interface_codes[name]['type']}", node
        )
