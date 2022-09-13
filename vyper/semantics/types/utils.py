from typing import Dict

from vyper import ast as vy_ast
from vyper.exceptions import InvalidType, UnknownType, StructureException
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.namespace import get_namespace
from vyper.semantics.types.base import VyperType


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
            sarray_t = namespace["$SArrayT"]
            return sarray_t(value_type, length)
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
        Vyper ast node from the `annotation` member of a `VariableDecl` or `AnnAssign` node.

    Returns
    -------
    VyperType
        Type definition object.
    """
    namespace = get_namespace()

    def _failwith(type_name):
        suggestions_str = get_levenshtein_error_suggestions(type_name, namespace, 0.3)
        raise UnknownType(
            f"No builtin or user-defined type named '{type_name}'. {suggestions_str}", node
        ) from None

    if isinstance(node, vy_ast.Tuple):
        tuple_t = namespace["$TupleT"]

        return tuple_t.from_annotation(node)

    if isinstance(node, vy_ast.Subscript):
        # ex. HashMap, DynArray, Bytes, static arrays
        if node.value.get("id") in ("HashMap", "Bytes", "String", "DynArray"):
            type_ctor = namespace[node.value.id]
        else:
            # like, address[5] or int256[5][5]
            type_ctor = namespace["$SArrayT"]

        return type_ctor.from_annotation(node)

    if not isinstance(node, vy_ast.Name):
        # maybe handle this somewhere upstream in ast validation
        raise StructureException("Not a type!", node)
    if node.id not in namespace:
        _failwith(node.node_source_code)

    return namespace[node.id]
