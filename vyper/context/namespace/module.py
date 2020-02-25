from vyper import (
    ast as vy_ast,
)
from vyper.context.datatypes.units import (
    Unit,
)
from vyper.context.events import (
    Event,
)
from vyper.context.functions import (
    Function,
)
from vyper.context.variables import (
    Variable,
)
from vyper.exceptions import (
    StructureException,
    VariableDeclarationException,
)


class ModuleNodeVisitor:

    def __init__(self, namespace, module_node, interface_codes):
        self.namespace = namespace
        self.interface_codes = interface_codes
        self.units_added = False
        module_nodes = module_node.body.copy()
        while module_nodes:
            count = len(module_nodes)
            for node in list(module_nodes):
                try:
                    self.visit(node)
                    module_nodes.remove(node)
                except Exception as e:
                    print(e)
                    continue
            if count == len(module_nodes):
                raise

    def visit(self, node):
        if isinstance(node, getattr(self, 'ignored_types', ())):
            return
        visitor_fn = getattr(self, f'visit_{node.ast_type}', None)
        if visitor_fn is None:
            raise StructureException(
                f"Unsupported syntax for module-level namespace: {node.ast_type}", node
            )
        visitor_fn(node)

    def visit_AnnAssign(self, node):
        if node.get('annotation.func.id') == "event":
            event = Event(self.namespace, node.target.id, node.annotation, node.value)
            self.namespace[node.target.id] = event
            return
        name = node.get('target.id')
        if name == "units":
            if self.units_added:
                raise VariableDeclarationException("Custom units can only be defined once", node)
            _add_custom_units(self.namespace, node)
        elif name == "implements":
            interface_name = node.annotation.id
            self.namespace[interface_name].validate_implements(self.namespace)
        else:
            var = Variable(self.namespace, node.target.id, node.annotation, node.value)
            self.namespace[node.target.id] = var

    def visit_ClassDef(self, node):
        self.namespace[node.name] = self.namespace[node.class_type].get_type(self.namespace, node)

    def visit_Import(self, node):
        _add_import(self.namespace, node, self.interface_codes)

    def visit_ImportFrom(self, node):
        _add_import(self.namespace, node, self.interface_codes)

    def visit_FunctionDef(self, node):
        self.namespace[node.name] = Function(self.namespace, node)


def _add_custom_units(namespace, node):
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
        namespace[key.id] = Unit(name=key.id, description=value.s, enclosing_scope="module")


def _add_import(namespace, node, interface_codes):
    if isinstance(node, vy_ast.Import):
        name = node.names[0].asname
    else:
        name = node.names[0].name
    # TODO handle json imports
    interface_ast = vy_ast.parse_to_ast(interface_codes[name]['code'])
    interface_ast.name = name
    namespace[name] = namespace['contract'].get_type(namespace, interface_ast)
