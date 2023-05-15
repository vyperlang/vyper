import warnings
from typing import Optional, Union

from vyper.ast import nodes as vy_ast
from vyper.builtins.functions import DISPATCH_TABLE
from vyper.exceptions import UnfoldableNode, UnknownType
from vyper.semantics.namespace import get_namespace, override_global_namespace
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.user import StructT
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

    # manually populate namespace with structs
    struct_defs = list(vyper_module.get_children(vy_ast.StructDef))  # explicit list cast for mypy
    namespace = get_namespace()
    with override_global_namespace(namespace):
        for struct_def in struct_defs:
            try:
                namespace[struct_def.name] = StructT.from_ast_def(struct_def)
            except UnknownType:
                continue

        for node in vyper_module.get_children(vy_ast.VariableDecl):
            if not isinstance(node.target, vy_ast.Name):
                # left-hand-side of assignment is not a variable
                continue
            if not node.is_constant:
                # annotation is not wrapped in `constant(...)`
                continue

            # Extract type definition from propagated annotation
            type_ = None
            try:
                type_ = type_from_annotation(node.annotation)
            except UnknownType:
                # handle structs defined out of order
                pass

            changed_nodes += replace_constant(
                vyper_module, node.target.id, node.value, False, type_=type_
            )

        # clear namespace to prevent collision in semantics pass
        namespace.clear()

    return changed_nodes


# TODO constant folding on log events


def _replace(old_node, new_node, type_=None):
    if isinstance(new_node, vy_ast.Constant):
        new_node = new_node.from_node(old_node, value=new_node.value)
        if type_:
            new_node._metadata["type"] = type_
        return new_node
    elif isinstance(new_node, vy_ast.List):
        base_type = type_.value_type if type_ else None
        list_values = [_replace(old_node, i, type_=base_type) for i in new_node.elements]
        new_node = new_node.from_node(old_node, elements=list_values)
        if type_:
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
        return new_node
    else:
        raise UnfoldableNode


def replace_constant(
    vyper_module: vy_ast.Module,
    id_: str,
    replacement_node: Union[vy_ast.Constant, vy_ast.List, vy_ast.Call],
    raise_on_error: bool,
    type_: Optional[VyperType] = None,
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
    type_ : VyperType, optional
        Type definition to be propagated to type checker.

    Returns
    -------
    int
        Number of nodes that were replaced.
    """
    changed_nodes = 0

    for node in vyper_module.get_descendants(vy_ast.Name, {"id": id_}, reverse=True):
        # store a copy in case it needs to be modified for structs
        propagated_type = type_
        propagated_node = replacement_node

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

        # derive the type and replacement node for struct members
        # and change the node to be replaced to the top level `vy_ast.Attribute` node
        # (i.e. the most nested attribute)
        if isinstance(parent, vy_ast.Attribute) and isinstance(type_, StructT):
            is_top_level = False

            while not is_top_level:
                member_name = parent.attr
                assert isinstance(propagated_node, vy_ast.Call)  # mypy hint
                values_dict = propagated_node.args[0]

                for k, v in zip(values_dict.keys, values_dict.values):
                    if k.id == member_name:
                        node = parent
                        propagated_node = v
                        assert isinstance(propagated_type, StructT)  # mypy hint
                        propagated_type = propagated_type.get_member(member_name, replacement_node)

                # move one level up in the AST (or one level down in the nested attribute)
                parent = parent.get_ancestor(vy_ast.Attribute)
                if parent is None:
                    is_top_level = True

        try:
            # note: _replace creates a copy of the replacement_node
            new_node = _replace(node, propagated_node, type_=propagated_type)
        except UnfoldableNode:
            if raise_on_error:
                raise
            continue

        changed_nodes += 1
        vyper_module.replace_in_tree(node, new_node)

    return changed_nodes
