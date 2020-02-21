from vyper import (
    ast as vy_ast,
)
from vyper.context.datatypes.units import (
    Unit,
)
from vyper.context.datatypes.variables import (
    Variable,
)
from vyper.context.datatypes.functions import (
    Function,
)
from vyper.context.datatypes.events import (
    Event,
)
from vyper.exceptions import (
    VariableDeclarationException,
    StructureException,
)


def add_custom_units(module_nodes, namespace):
    # extracts custom unit information from AST
    # verifies correctness of custom units and that they are declared at most once

    units_nodes = [
        i for i in module_nodes if isinstance(i, vy_ast.AnnAssign) and i.get('target.id') == "units"
    ]
    if not units_nodes:
        return module_nodes, namespace

    if len(units_nodes) > 1:
        raise VariableDeclarationException(
            "Custom units can only be defined once", units_nodes[1]
        )

    node = units_nodes[0]
    module_nodes.remove(node)

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

    return module_nodes, namespace


def add_custom_types(module_nodes, namespace):
    _add_imports(module_nodes, namespace)
    _add_classes(module_nodes, namespace)
    # TODO add functions
    # implements ?

    return module_nodes, namespace


def _add_imports(module_nodes, namespace):
    for node in [i for i in module_nodes if isinstance(i, vy_ast.Import)]:
        namespace[node.names[0].asname] = namespace['contract'].get_meta_type(namespace, node)
        module_nodes.remove(node)

    for node in [i for i in module_nodes if isinstance(i, vy_ast.ImportFrom)]:
        namespace[node.names[0].name] = namespace['contract'].get_meta_type(namespace, node)
        module_nodes.remove(node)


def _add_classes(module_nodes, namespace):
    for node in [i for i in module_nodes if isinstance(i, vy_ast.ClassDef)]:
        namespace[node.name] = namespace[node.class_type].get_meta_type(namespace, node)
        module_nodes.remove(node)


def add_functions(module_nodes, namespace):
    for node in [i for i in module_nodes if isinstance(i, vy_ast.FunctionDef)]:
        # TODO check for node.simple
        namespace[node.name] = Function(namespace, node)
        module_nodes.remove(node)

    return module_nodes, namespace


def add_events(module_nodes, namespace):
    for node in [i for i in module_nodes if i.get('annotation.func.id') == "event"]:
        namespace[node.target.id] = Event(namespace, node.target.id, node.annotation, node.value)
        module_nodes.remove(node)

    return module_nodes, namespace


def add_variables(module_nodes, namespace):
    for node in [i for i in module_nodes if isinstance(i, vy_ast.AnnAssign)]:
        if node.target.id == "implements":
            continue
        namespace[node.target.id] = Variable(namespace, node.target.id, node.annotation, node.value)
        module_nodes.remove(node)

    return module_nodes, namespace


def add_implemented_interfaces(module_nodes, namespace):
    implement_nodes = [
        i for i in module_nodes if isinstance(i, vy_ast.AnnAssign)
        and i.get('target.id') == "implements"
    ]
    interface_names = set()
    for node in implement_nodes:
        name = node.annotation.id
        if name in interface_names:
            raise StructureException("Interface has already been implemented", node)
        module_nodes.remove(node)
        interface_names.add(name)

    for name in interface_names:
        namespace[name].validate_implements(namespace)

    return module_nodes, namespace
