from typing import Dict

from vyper import ast as vy_ast
from vyper.context.namespace import get_namespace
from vyper.context.types.bases import BaseTypeDefinition
from vyper.context.types.indexable.sequence import ArrayDefinition
from vyper.context.validation.utils import (
    get_exact_type_from_node,
    get_index_value,
)
from vyper.exceptions import (
    InvalidType,
    StructureException,
    UndeclaredDefinition,
    UnknownType,
)


def get_type_from_abi(
    abi_type: Dict, is_constant: bool = False, is_public: bool = False
) -> BaseTypeDefinition:
    """
    Return a type object from an ABI type definition.

    Arguments
    ---------
    abi_type : Dict
       A type definition taken from the `input` or `output` field of an ABI.

    Returns
    -------
    BaseTypeDefinition
        Type definition object.
    """
    type_string = abi_type["type"]
    if type_string == "fixed168x10":
        type_string = "decimal"
    # TODO string and bytes

    namespace = get_namespace()

    if "[" in type_string:
        value_type_string, length_str = type_string.rsplit("[", maxsplit=1)
        try:
            length = int(length_str.rstrip("]"))
        except ValueError:
            raise UnknownType(f"ABI type has an invalid length: {type_string}") from None
        try:
            value_type = get_type_from_abi({"type": value_type_string}, is_constant=is_constant)
        except UnknownType:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None
        try:
            return ArrayDefinition(value_type, length, is_constant, is_public)
        except InvalidType:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None

    else:
        try:
            return namespace[type_string]._type(is_constant=is_constant, is_public=is_public)
        except KeyError:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None


def get_type_from_annotation(
    node: vy_ast.VyperNode, is_constant: bool = False, is_public: bool = False
) -> BaseTypeDefinition:
    """
    Return a type object for the given AST node.

    Arguments
    ---------
    node : VyperNode
        Vyper ast node from the `annotation` member of an `AnnAssign` node.

    Returns
    -------
    BaseTypeDefinition
        Type definition object.
    """
    namespace = get_namespace()
    try:
        # get id of leftmost `Name` node from the annotation
        type_name = next(i.id for i in node.get_descendants(vy_ast.Name, include_self=True))
        type_obj = namespace[type_name]
    except StopIteration:
        raise StructureException("Invalid syntax for type declaration", node)
    except UndeclaredDefinition:
        raise UnknownType("Not a valid type - value is undeclared", node) from None

    if getattr(type_obj, "_as_array", False) and isinstance(node, vy_ast.Subscript):
        # if type can be an array and node is a subscript, create an `ArrayDefinition`
        length = get_index_value(node.slice)
        value_type = get_type_from_annotation(node.value, is_constant, False)
        return ArrayDefinition(value_type, length, is_constant, is_public)

    try:
        return type_obj.from_annotation(node, is_constant, is_public)
    except AttributeError:
        raise UnknownType(f"'{type_name}' is not a valid type", node) from None


def check_literal(node: vy_ast.VyperNode) -> bool:
    """
    Check if the given node is a literal value.
    """
    if isinstance(node, vy_ast.Constant):
        return True
    elif isinstance(node, (vy_ast.Tuple, vy_ast.List)):
        for item in node.elements:
            if not check_literal(item):
                return False
        return True
    else:
        return False


def check_constant(node: vy_ast.VyperNode) -> bool:
    """
    Check if the given node is a literal or constant value.
    """
    if check_literal(node):
        return True
    if isinstance(node, (vy_ast.Tuple, vy_ast.List)):
        for item in node.elements:
            if not check_constant(item):
                return False
        return True

    value_type = get_exact_type_from_node(node)
    return getattr(value_type, "is_constant", False)
