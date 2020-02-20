from vyper import (
    ast as vy_ast,
)
from vyper.context.datatypes.units import (
    Unit,
)
from vyper.context.datatypes.variables import (
    Variable,
)
from vyper.exceptions import (
    VariableDeclarationException,
)


def add_custom_units(global_nodes, namespace):
    # extracts custom unit information from AST
    # verifies correctness of custom units and that they are declared at most once

    units_nodes = [
        i for i in global_nodes if isinstance(i, vy_ast.AnnAssign) and i.get('target.id') == "units"
    ]
    if not units_nodes:
        return global_nodes, namespace

    if len(units_nodes) > 1:
        raise VariableDeclarationException(
            "Custom units can only be defined once", units_nodes[1]
        )

    node = units_nodes[0]
    global_nodes.remove(node)

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

    return global_nodes, namespace


def add_custom_types(global_nodes, namespace):
    _add_imports(global_nodes, namespace)
    _add_classes(global_nodes, namespace)
    # TODO add functions
    # implements ?

    return global_nodes, namespace


def _add_imports(global_nodes, namespace):
    for node in [i for i in global_nodes if isinstance(i, vy_ast.Import)]:
        namespace[node.names[0].asname] = namespace['contract'].get_meta_type(node)
        global_nodes.remove(node)

    for node in [i for i in global_nodes if isinstance(i, vy_ast.ImportFrom)]:
        namespace[node.names[0].name] = namespace['contract'].get_meta_type(node)
        global_nodes.remove(node)


def _add_classes(global_nodes, namespace):
    for node in [i for i in global_nodes if isinstance(i, vy_ast.ClassDef)]:
        namespace[node.name] = namespace[node.class_type].get_meta_type(node)
        global_nodes.remove(node)


def add_assignments(global_nodes, namespace):
    for node in [i for i in global_nodes if isinstance(i, vy_ast.AnnAssign)]:
        if node.target.id in ("implements", "units"):
            continue
        var = Variable(namespace, node)
        namespace[var.name] = var
        global_nodes.remove(node)

    return global_nodes, namespace
