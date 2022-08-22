import enum
from typing import Dict, List

from vyper import ast as vy_ast
from vyper.exceptions import (
    CompilerPanic,
    InvalidType,
    StructureException,
    UndeclaredDefinition,
    UnknownType,
    VyperInternalException,
)
from vyper.semantics.namespace import get_namespace
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.subscriptable import SArrayT, TupleT
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.analysis.utils import get_index_value


def type_from_abi(abi_type: Dict) -> VyperType:
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
    if type_string in ("string", "bytes"):
        type_string = type_string.capitalize()

    namespace = get_namespace()

    if "[" in type_string:
        value_type_string, length_str = type_string.rsplit("[", maxsplit=1)
        try:
            length = int(length_str.rstrip("]"))
        except ValueError:
            raise UnknownType(f"ABI type has an invalid length: {type_string}") from None
        try:
            value_type = type_from_abi({"type": value_type_string})
        except UnknownType:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None
        try:
            return SArrayT(value_type, length)
        except InvalidType:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None

    else:
        try:
            return namespace[type_string]
        except KeyError:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None


def type_from_annotation(node: vy_ast.VyperNode) -> VyperType:
    """
    Return a type object for the given AST node.

    Arguments
    ---------
    node : VyperNode
        Vyper ast node from the `annotation` member of a `VariableDef` or `AnnAssign` node.

    Returns
    -------
    VyperType
        Type definition object.
    """
    namespace = get_namespace()

    if isinstance(node, vy_ast.Tuple):
        values = node.elements
        types = tuple(type_from_annotation(v) for v in values)
        return TupleT(types)

    try:
        # get id of leftmost `Name` node from the annotation
        type_name = next(i.id for i in node.get_descendants(vy_ast.Name, include_self=True))
    except StopIteration:
        raise StructureException("Invalid syntax for type declaration", node)
    try:
        typeclass = namespace[type_name]
    except UndeclaredDefinition:
        suggestions_str = get_levenshtein_error_suggestions(type_name, namespace, 0.3)
        raise UnknownType(
            f"No builtin or user-defined type named '{type_name}'. {suggestions_str}", node
        ) from None

    if (
        getattr(typeclass, "_as_array", False)
        and isinstance(node, vy_ast.Subscript)
        and node.value.get("id") != "DynArray"
    ):
        # TODO: handle `is_immutable` for arrays
        # if type can be an array and node is a subscript, create an `SArrayT`
        length = get_index_value(node.slice)
        value_type = type_from_annotation(node.value)
        return SArrayT(value_type, length)

    if not isinstance(typeclass, type):
        return typeclass

    try:
        return typeclass.from_annotation(node)
    except AttributeError:
        raise InvalidType(f"'{type_name}' is not a valid type", node) from None
