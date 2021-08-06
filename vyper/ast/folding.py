from decimal import Decimal
from typing import Union

from vyper.ast import nodes as vy_ast
from vyper.builtin_functions import DISPATCH_TABLE
from vyper.exceptions import UnfoldableNode

BUILTIN_CONSTANTS = {
    "EMPTY_BYTES32": (
        vy_ast.Hex,
        "0x0000000000000000000000000000000000000000000000000000000000000000",
    ),  # NOQA: E501
    "ZERO_ADDRESS": (vy_ast.Hex, "0x0000000000000000000000000000000000000000"),
    "MAX_INT128": (vy_ast.Int, 2 ** 127 - 1),
    "MIN_INT128": (vy_ast.Int, -(2 ** 127)),
    "MAX_DECIMAL": (vy_ast.Decimal, Decimal(2 ** 127 - 1)),
    "MIN_DECIMAL": (vy_ast.Decimal, Decimal(-(2 ** 127))),
    "MAX_UINT256": (vy_ast.Int, 2 ** 256 - 1),
}


def fold(vyper_module: vy_ast.Module) -> None:
    """
    Perform literal folding operations on a Vyper AST.

    Arguments
    ---------
    vyper_module : Module
        Top-level Vyper AST node.
    """
    replace_builtin_constants(vyper_module)

    changed_nodes = 1
    while changed_nodes:
        changed_nodes = 0
        changed_nodes += replace_user_defined_constants(vyper_module)
        changed_nodes += replace_literal_ops(vyper_module)
        changed_nodes += replace_subscripts(vyper_module)
        changed_nodes += replace_builtin_functions(vyper_module)


def replace_literal_ops(vyper_module: vy_ast.Module) -> int:
    """
    Find and evaluate operation and comparison nodes within the Vyper AST,
    replacing them with Constant nodes where possible.

    Arguments
    ---------
    vyper_module : Module
        Top-level Vyper AST node.

    Returns
    -------
    int
        Number of nodes that were replaced.
    """
    changed_nodes = 0

    node_types = (vy_ast.BoolOp, vy_ast.BinOp, vy_ast.UnaryOp, vy_ast.Compare)
    for node in vyper_module.get_descendants(node_types, reverse=True):
        try:
            new_node = node.evaluate()
        except UnfoldableNode:
            continue

        changed_nodes += 1
        vyper_module.replace_in_tree(node, new_node)

    return changed_nodes


def replace_subscripts(vyper_module: vy_ast.Module) -> int:
    """
    Find and evaluate Subscript nodes within the Vyper AST, replacing them with
    Constant nodes where possible.

    Arguments
    ---------
    vyper_module : Module
        Top-level Vyper AST node.

    Returns
    -------
    int
        Number of nodes that were replaced.
    """
    changed_nodes = 0

    for node in vyper_module.get_descendants(vy_ast.Subscript, reverse=True):
        try:
            new_node = node.evaluate()
        except UnfoldableNode:
            continue

        changed_nodes += 1
        vyper_module.replace_in_tree(node, new_node)

    return changed_nodes


def replace_builtin_functions(vyper_module: vy_ast.Module) -> int:
    """
    Find and evaluate builtin function calls within the Vyper AST, replacing
    them with Constant nodes where possible.

    Arguments
    ---------
    vyper_module : Module
        Top-level Vyper AST node.

    Returns
    -------
    int
        Number of nodes that were replaced.
    """
    changed_nodes = 0

    for node in vyper_module.get_descendants(vy_ast.Call, reverse=True):
        if not isinstance(node.func, vy_ast.Name):
            continue

        name = node.func.id
        func = DISPATCH_TABLE.get(name)
        if func is None or not hasattr(func, "evaluate"):
            continue
        try:
            new_node = func.evaluate(node)  # type: ignore
        except UnfoldableNode:
            continue

        changed_nodes += 1
        vyper_module.replace_in_tree(node, new_node)

    return changed_nodes


def replace_builtin_constants(vyper_module: vy_ast.Module) -> None:
    """
    Replace references to builtin constants with their literal values.

    Arguments
    ---------
    vyper_module : Module
        Top-level Vyper AST node.
    """
    for name, (node, value) in BUILTIN_CONSTANTS.items():
        replace_constant(vyper_module, name, node(value=value), True)  # type: ignore


def replace_user_defined_constants(vyper_module: vy_ast.Module) -> int:
    """
    Find user-defined constant assignments, and replace references
    to the constants with their literal values.

    Arguments
    ---------
    vyper_module : Module
        Top-level Vyper AST node.

    Returns
    -------
    int
        Number of nodes that were replaced.
    """
    changed_nodes = 0

    for node in vyper_module.get_children(vy_ast.AnnAssign):
        if not isinstance(node.target, vy_ast.Name):
            # left-hand-side of assignment is not a variable
            continue
        if node.get("annotation.func.id") != "constant":
            # annotation is not wrapped in `constant(...)`
            continue

        changed_nodes += replace_constant(vyper_module, node.target.id, node.value, False)

    return changed_nodes


# TODO constant folding on log events


def _replace(old_node, new_node):
    if isinstance(new_node, vy_ast.Constant):
        return new_node.from_node(old_node, value=new_node.value)
    elif isinstance(new_node, vy_ast.List):
        list_values = [_replace(old_node, i) for i in new_node.elements]
        return new_node.from_node(old_node, elements=list_values)
    else:
        raise UnfoldableNode


def replace_constant(
    vyper_module: vy_ast.Module,
    id_: str,
    replacement_node: Union[vy_ast.Constant, vy_ast.List],
    raise_on_error: bool,
) -> int:
    """
    Replace references to a variable name with a literal value.

    Arguments
    ---------
    vyper_module : Module
        Module-level ast node to perform replacement in.
    id_ : str
        String representing the `.id` attribute of the node(s) to be replaced.
    replacement_node : Constant | List
        Vyper ast node representing the literal value to be substituted in.
    raise_on_error: bool
        Boolean indicating if `UnfoldableNode` exception should be raised or ignored.

    Returns
    -------
    int
        Number of nodes that were replaced.
    """
    changed_nodes = 0

    for node in vyper_module.get_descendants(vy_ast.Name, {"id": id_}, reverse=True):
        parent = node.get_ancestor()

        if isinstance(parent, vy_ast.Attribute):
            # do not replace attributes
            continue
        if isinstance(parent, vy_ast.Call) and node == parent.func:
            # do not replace calls
            continue

        # do not replace dictionary keys
        if isinstance(parent, vy_ast.Dict) and node in parent.keys:
            continue

        if not node.get_ancestor(vy_ast.Index):
            # do not replace left-hand side of assignments
            assign = node.get_ancestor((vy_ast.Assign, vy_ast.AnnAssign, vy_ast.AugAssign))

            if assign and node in assign.target.get_descendants(include_self=True):
                continue

        try:
            new_node = _replace(node, replacement_node)
        except UnfoldableNode:
            if raise_on_error:
                raise
            continue

        changed_nodes += 1
        vyper_module.replace_in_tree(node, new_node)

    return changed_nodes
