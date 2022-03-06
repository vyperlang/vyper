from decimal import Decimal
from typing import List, Optional, Union

from vyper.ast import nodes as vy_ast
from vyper.builtin_functions import DISPATCH_TABLE
from vyper.exceptions import UnfoldableNode, UnknownType
from vyper.semantics.types.bases import BaseTypeDefinition, DataLocation
from vyper.semantics.types.utils import get_type_from_annotation

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

        # Extract type definition from propagated annotation
        constant_annotation = node.get("annotation.args")[0]
        try:
            type_ = (
                get_type_from_annotation(constant_annotation, DataLocation.UNSET)
                if constant_annotation
                else None
            )
        except UnknownType:
            # handle user-defined types e.g. structs - it's OK to not
            # propagate the type annotation here because user-defined
            # types can be unambiguously inferred at typechecking time
            type_ = None

        changed_nodes += replace_constant(
            vyper_module, node.target.id, node.value, False, type_=type_
        )

        if isinstance(node.value, vy_ast.Call) and len(node.value.args) == 1:
            if isinstance(node.value.args[0], vy_ast.Dict):

                # If struct, replace references to each struct member with
                # its literal value
                struct_dict = node.value.args[0]

                # Pass empty list of parent attributes for first call to struct members
                # helper function
                changed_nodes = _replace_struct_members(
                    vyper_module, struct_dict, node.target.id, changed_nodes, []
                )

    return changed_nodes


def _replace_struct_members(
    vyper_module: vy_ast.Module,
    dict_node: vy_ast.Dict,
    id_: str,
    changed_nodes: int,
    parent_attribute_ids: List[str],
) -> int:
    """
    Helper function to recursively replace nested structs members

    Arguments
    ---------
    vyper_module : Module
        Top-level Vyper AST node.
    dict_node: Dict
        Vyper AST node representing the dict of a struct
    id_: str
        String representing the `.id` attribute of the node(s) to be replaced.
        To be passed to replace_constant.
    changed_nodes: int
        Count of Vyper AST nodes that are to be replaced.
    parent_attribute_ids: List[str], optional
        List of parent attributes (representing the `.attr` attribute of an `Attribute` node)
        that should be traceable from the node to be replaced.
        Used to determine when a nested struct should be replaced.
    Returns
    -------
    int
        Number of nodes that were replaced.
    """
    for k, v in zip(dict_node.keys, dict_node.values):

        if isinstance(v, vy_ast.Call) and isinstance(v.args[0], vy_ast.Dict):

            # For nested structs, recursively replace the struct members based on
            # the current level of nesting (i.e. Dict node)
            new_struct_dict = v.args[0]

            # Add current key's ID (i.e. struct member name) to a new parent attributes list
            # A new list is needed in order to generate the correct paths for each key
            new_parent_attribute_ids = parent_attribute_ids
            if k.id not in parent_attribute_ids:
                new_parent_attribute_ids = parent_attribute_ids + [k.id]

            # Recursive call to handle the next nested struct
            changed_nodes = _replace_struct_members(
                vyper_module,
                new_struct_dict,
                id_,
                changed_nodes,
                new_parent_attribute_ids,
            )

        # If parent attributes are present, handle as nested structs
        # Call replace_constant with parent attributes instead of the attribute id.
        changed_nodes += replace_constant(
            vyper_module, id_, v, False, parent_attribute_ids=parent_attribute_ids + [k.id]
        )

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


def _get_struct_attribute_root_node(
    parent_attribute_node: vy_ast.VyperNode,
    parent_attribute_ids: List[str],
) -> Optional[vy_ast.Attribute]:
    """
    Helper function to return the root node of a constant struct member that should be replaced.

    E.g. Assuming `Foo` is a constant struct with a nested struct `a`, that has a `b` member,
    a reference to the nested constant `Foo.a.b` will be represented in the AST as:

    `b`  (`Attribute` node)
     |---> `a` (`Attribute` node)
            |---> `Foo` (`Name` node)

    To fold this constant, we need to identify `b` as the root node to be replaced.

    Arguments
    ---------
    parent_attribute_node : VyperNode
        Vyper ast node that is the parent to a `Name` node for a struct member
    parent_attribute_ids: List[str], optional
        List of parent attributes (representing the `.attr` attribute of an `Attribute` node)
        that should be traceable from the node to be replaced.
        Used to further filter nodes successively after getting descendants based on `id_`.
        Used to propagate nested struct names and struct member names (both plain and nested).

    Returns
    -------
    Attribute, optional
        Vyper ast node that is the root of a constant struct member in the AST.
    """

    node_to_be_replaced = None
    for i in range(len(parent_attribute_ids)):
        if not isinstance(parent_attribute_node, vy_ast.Attribute):
            # If current parent is not an Attribute node,
            # but there is an attribute to be checked, skip.
            break

        # Iterate through the list of parent attributes
        if parent_attribute_node.attr != parent_attribute_ids[i]:
            # Early termination if parent attribute does not match current node path
            break

        if i == len(parent_attribute_ids) - 1 and not hasattr(
            parent_attribute_node.get_ancestor(), "attr"
        ):
            # If all attributes match, and the current parent is not a nested member,
            # continue with the replacement. Otherwise, skip replacement.
            node_to_be_replaced = parent_attribute_node

        # Continue iteration until all parent attributes are checked
        parent_attribute_node = parent_attribute_node.get_ancestor()

    # Only replace if all parent attributes match. Otherwise, skip.
    return node_to_be_replaced


def replace_constant(
    vyper_module: vy_ast.Module,
    id_: str,
    replacement_node: Union[vy_ast.Constant, vy_ast.List, vy_ast.Call],
    raise_on_error: bool,
    type_: BaseTypeDefinition = None,
    parent_attribute_ids: List[str] = None,
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
        `Call` nodes are for whole struct constants.
    raise_on_error: bool
        Boolean indicating if `UnfoldableNode` exception should be raised or ignored.
    type_ : BaseTypeDefinition, optional
        Type definition to be propagated to type checker.
    parent_attribute_ids: List[str], optional
        List of parent attributes (representing the `.attr` attribute of an `Attribute` node)
        that should be traceable from the node to be replaced.
        Used to further filter nodes successively after getting descendants based on `id_`.
        Used to propagate nested struct names and struct member names (both plain and nested).

    Returns
    -------
    int
        Number of nodes that were replaced.
    """
    is_struct = False

    # Set is_struct to true if entire top-level struct constant is being replaced
    if isinstance(replacement_node, vy_ast.Call) and len(replacement_node.args) == 1:
        if isinstance(replacement_node.args[0], vy_ast.Dict):
            is_struct = True

    # Set is_struct to true if struct member id is provided
    # Used for struct members (plain and nested) and nested structs
    if parent_attribute_ids:
        is_struct = True

    changed_nodes = 0

    for node in vyper_module.get_descendants(vy_ast.Name, {"id": id_}, reverse=True):
        parent = node.get_ancestor()

        if isinstance(parent, vy_ast.Call) and node == parent.func:
            # do not replace calls that are not structs
            if not is_struct:
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
            new_node = _replace(node, replacement_node, type_=type_)
        except UnfoldableNode:
            if raise_on_error:
                raise
            continue

        changed_nodes += 1
        vyper_module.replace_in_tree(node, new_node)

    return changed_nodes
