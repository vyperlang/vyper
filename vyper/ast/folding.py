import warnings
from typing import Optional, Union

from vyper.ast import nodes as vy_ast
from vyper.builtins.functions import DISPATCH_TABLE
from vyper.exceptions import UnfoldableNode, UnknownType
from vyper.semantics.analysis.base import DataLocation, ExprInfo
from vyper.semantics.types.utils import type_from_annotation
from vyper.utils import SizeLimits

BUILTIN_CONSTANTS = {
    "EMPTY_BYTES32": (
        vy_ast.Hex,
        "0x0000000000000000000000000000000000000000000000000000000000000000",
        "empty(bytes32)",
    ),  # NOQA: E501
    "ZERO_ADDRESS": (vy_ast.Hex, "0x0000000000000000000000000000000000000000", "empty(address)"),
    "MAX_INT128": (vy_ast.Int, 2**127 - 1, "max_value(int128)"),
    "MIN_INT128": (vy_ast.Int, -(2**127), "min_value(int128)"),
    "MAX_DECIMAL": (vy_ast.Decimal, SizeLimits.MAX_AST_DECIMAL, "max_value(decimal)"),
    "MIN_DECIMAL": (vy_ast.Decimal, SizeLimits.MIN_AST_DECIMAL, "min_value(decimal)"),
    "MAX_UINT256": (vy_ast.Int, 2**256 - 1, "max_value(uint256)"),
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
    for name, (node, value, replacement) in BUILTIN_CONSTANTS.items():
        found = replace_constant(vyper_module, name, node(value=value), True)
        if found > 0:
            warnings.warn(f"{name} is deprecated. Please use `{replacement}` instead.")


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
        if not isinstance(node.target, vy_ast.Name):
            # left-hand-side of assignment is not a variable
            continue
        if not node.is_constant:
            # annotation is not wrapped in `constant(...)`
            continue

        # Extract type definition from propagated annotation
        type_ = None
        expr_info = None
        try:
            type_ = type_from_annotation(node.annotation)
            expr_info = ExprInfo(
                type_,
                location=DataLocation.CODE,
                is_constant=node.is_constant,
                is_immutable=node.is_immutable,
            )

        except UnknownType:
            # handle user-defined types e.g. structs - it's OK to not
            # propagate the type annotation here because user-defined
            # types can be unambiguously inferred at typechecking time
            pass

        changed_nodes += replace_constant(
            vyper_module, node.target.id, node.value, False, expr_info=expr_info
        )

    return changed_nodes


# TODO constant folding on log events


def _replace(old_node, new_node, expr_info=None):
    if isinstance(new_node, vy_ast.Constant):
        new_node = new_node.from_node(old_node, value=new_node.value)
        if expr_info is not None:
            new_node._metadata["exprinfo"] = expr_info
        return new_node
    elif isinstance(new_node, vy_ast.List):
        base_type_exprinfo = None
        if expr_info is not None:
            base_type_exprinfo = ExprInfo(
                typ=expr_info.typ.value_type,
                location=DataLocation.CODE,
                is_constant=expr_info.is_constant,
                is_immutable=expr_info.is_immutable,
            )
        list_values = [
            _replace(old_node, i, expr_info=base_type_exprinfo) for i in new_node.elements
        ]
        new_node = new_node.from_node(old_node, elements=list_values)
        if expr_info is not None:
            new_node._metadata["exprinfo"] = expr_info
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
        return new_node
    else:
        raise UnfoldableNode


def replace_constant(
    vyper_module: vy_ast.Module,
    id_: str,
    replacement_node: Union[vy_ast.Constant, vy_ast.List, vy_ast.Call],
    raise_on_error: bool,
    expr_info: Optional[ExprInfo] = None,
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
    raise_on_error: bool
        Boolean indicating if `UnfoldableNode` exception should be raised or ignored.
    expr_info : ExprInfo, optional
        Type definition plus associated metadata like constancy attributes to be
        propagated to type checker.

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
            new_node = _replace(node, replacement_node, expr_info=expr_info)
        except UnfoldableNode:
            if raise_on_error:
                raise
            continue

        changed_nodes += 1
        vyper_module.replace_in_tree(node, new_node)

    return changed_nodes
