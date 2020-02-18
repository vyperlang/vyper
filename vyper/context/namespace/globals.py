from vyper import (
    ast as vy_ast,
)
from vyper.context.datatypes.units import (
    Unit,
)
from vyper.context.datatypes.variables import (
    Variable,
)
from vyper.context.utils import (
    check_global_scope,
)
from vyper.exceptions import (
    VariableDeclarationException,
)


def add_custom_units(vy_module, namespace):
    # extracts custom unit information from AST
    # verifies correctness of custom units and that they are declared at most once

    node_list = vy_module.get_all_children({
        'ast_type': "AnnAssign",
        'annotation.ast_type': "Dict",
        'target.id': "units",
    })
    if not node_list:
        return namespace

    if len(node_list) > 1:
        raise VariableDeclarationException(
            "Custom units can only be defined once", node_list[1]
        )
    node = node_list[0]
    check_global_scope(node, "custom units")

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

    return namespace


def add_custom_types(vy_module, namespace):
    _add_imports(vy_module, namespace)
    _add_classes(vy_module, namespace)
    # TODO add functions
    # implements ?

    return namespace


def _add_imports(vy_module, namespace):
    for node in vy_module.get_children({'ast_type': "Import"}):
        namespace[node.names[0].asname] = namespace['contract'].get_meta_type(node)
    for node in vy_module.get_children({'ast_type': "ImportFrom"}):
        namespace[node.names[0].name] = namespace['contract'].get_meta_type(node)


def _add_classes(vy_module, namespace):
    for node in vy_module.get_children({'ast_type': "ClassDef"}):
        namespace[node.name] = namespace[node.class_type].get_meta_type(node)


def add_assignments(vy_module, namespace):
    for node in vy_module.get_children({'ast_type': "AnnAssign"}):
        if node.target.id in ("implements", "units"):
            continue
        var = Variable(namespace, node)
        namespace[var.name] = var
    return namespace
