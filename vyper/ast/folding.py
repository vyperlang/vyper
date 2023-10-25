from typing import Union

from vyper.ast import nodes as vy_ast
from vyper.exceptions import UnfoldableNode
from vyper.semantics.types.base import VyperType


def fold(vyper_module: vy_ast.Module) -> None:
    """
    Perform literal folding operations on a Vyper AST.

    Arguments
    ---------
    vyper_module : Module
        Top-level Vyper AST node.
    """
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

        typ = node._metadata.get("type")

        # type metadata may not be present
        # e.g. type annotations (`DynArray[uint256, 2**8]`)
        if typ is not None:
            new_node._metadata["type"] = typ

            # defer literal validation until folding is no longer possible
            if not isinstance(node.get_ancestor(), node_types):
                typ.validate_literal(new_node)

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

        func = node.func._metadata.get("type")
        if func is None or not hasattr(func, "evaluate"):
            continue

        try:
            new_node = func.evaluate(node)  # type: ignore
        except UnfoldableNode:
            continue

        #print(node._metadata["type"])
        new_node._metadata["type"] = node._metadata["type"]

        changed_nodes += 1
        vyper_module.replace_in_tree(node, new_node)

    return changed_nodes


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

    for node in vyper_module.get_children(vy_ast.VariableDecl):
        if not node.is_constant:
            # annotation is not wrapped in `constant(...)`
            continue

        type_ = node._metadata["type"]
        changed_nodes += replace_constant(vyper_module, node.target.id, node.value, type_, False)

    return changed_nodes


# TODO constant folding on log events


def _replace(old_node, new_node, type_):
    if isinstance(new_node, vy_ast.Constant):
        new_node = new_node.from_node(old_node, value=new_node.value)
        new_node._metadata["type"] = type_
        return new_node
    elif isinstance(new_node, vy_ast.List):
        base_type = type_.value_type if type_ else None
        list_values = [_replace(old_node, i, type_=base_type) for i in new_node.elements]
        new_node = new_node.from_node(old_node, elements=list_values)
        new_node._metadata["type"] = type_
        return new_node
    elif isinstance(new_node, vy_ast.Call):
        # Replace `Name` node with `Call` node
        keyword = keywords = None
        if hasattr(new_node, "keyword"):
            keyword = new_node.keyword
        if hasattr(new_node, "keywords"):
            keywords = new_node.keywords
        new_node = new_node.from_node(
            old_node, func=new_node.func, args=new_node.args, keyword=keyword, keywords=keywords
        )
        new_node._metadata["type"] = type_
        return new_node
    else:
        raise UnfoldableNode


def replace_constant(
    vyper_module: vy_ast.Module,
    id_: str,
    replacement_node: Union[vy_ast.Constant, vy_ast.List, vy_ast.Call],
    type_: VyperType,
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
    replacement_node : Constant | List | Call
        Vyper ast node representing the literal value to be substituted in.
        `Call` nodes are for struct constants.
    type_ : VyperType
        Type definition to be propagated to type checker.
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

        if isinstance(parent, vy_ast.Call) and node == parent.func:
            # do not replace calls because splicing a constant into a callable site is
            # never valid and it worsens the error message
            continue

        # do not replace dictionary keys
        if isinstance(parent, vy_ast.Dict) and node in parent.keys:
            continue

        if not node.get_ancestor(vy_ast.Index):
            # do not replace left-hand side of assignments
            assign = node.get_ancestor(
                (vy_ast.Assign, vy_ast.AnnAssign, vy_ast.AugAssign, vy_ast.VariableDecl)
            )

            if assign and node in assign.target.get_descendants(include_self=True):
                continue

        # do not replace enum members
        if node.get_ancestor(vy_ast.EnumDef):
            continue

        try:
            # note: _replace creates a copy of the replacement_node
            new_node = _replace(node, replacement_node, type_)
        except UnfoldableNode:
            if raise_on_error:
                raise
            continue

        changed_nodes += 1
        vyper_module.replace_in_tree(node, new_node)

    return changed_nodes
