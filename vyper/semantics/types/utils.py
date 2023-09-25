from typing import Dict

from vyper import ast as vy_ast
from vyper.exceptions import (
    ArrayIndexException,
    InstantiationException,
    InvalidType,
    StructureException,
    UnfoldableNode,
    UnknownType,
    VyperException,
)
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.namespace import get_namespace
from vyper.semantics.types.base import VyperType

# TODO maybe this should be merged with .types/base.py


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
        # handle dynarrays, static arrays
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
            t = namespace[type_string]
            if type_string in ("Bytes", "String"):
                # special handling for bytes, string, since
                # the type ctor is in the namespace instead of a concrete type.
                return t()
            return t
        except KeyError:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None


def type_from_annotation(
    node: vy_ast.VyperNode, location: DataLocation = DataLocation.UNSET
) -> VyperType:
    """
    Return a type object for the given AST node after validating its location.

    Arguments
    ---------
    node : VyperNode
        Vyper ast node from the `annotation` member of a `VariableDecl` or `AnnAssign` node.

    Returns
    -------
    VyperType
        Type definition object.
    """
    typ_ = _type_from_annotation(node)

    if location in typ_._invalid_locations:
        location_str = "" if location is DataLocation.UNSET else f"in {location.name.lower()}"
        raise InstantiationException(f"{typ_} is not instantiable {location_str}", node)

    return typ_


def _type_from_annotation(node: vy_ast.VyperNode) -> VyperType:
    namespace = get_namespace()

    def _failwith(type_name):
        suggestions_str = get_levenshtein_error_suggestions(type_name, namespace, 0.3)
        raise UnknownType(
            f"No builtin or user-defined type named '{type_name}'. {suggestions_str}", node
        ) from None

    if isinstance(node, vy_ast.Tuple):
        tuple_t = namespace["$TupleT"]
        return tuple_t.from_annotation(node, namespace._constants)

    if isinstance(node, vy_ast.Subscript):
        # ex. HashMap, DynArray, Bytes, static arrays
        if node.value.get("id") in ("HashMap", "Bytes", "String", "DynArray"):
            assert isinstance(node.value, vy_ast.Name)  # mypy hint
            type_ctor = namespace[node.value.id]
        else:
            # like, address[5] or int256[5][5]
            type_ctor = namespace["$SArrayT"]

        return type_ctor.from_annotation(node, namespace._constants)

    if not isinstance(node, vy_ast.Name):
        # maybe handle this somewhere upstream in ast validation
        raise InvalidType(f"'{node.node_source_code}' is not a type", node)
    if node.id not in namespace:
        _failwith(node.node_source_code)

    typ_ = namespace[node.id]
    if hasattr(typ_, "from_annotation"):
        # cases where the object in the namespace is an uninstantiated
        # type object, ex. Bytestring or DynArray (with no length provided).
        # call from_annotation to produce a better error message.
        typ_.from_annotation(node, namespace._constants)

    return typ_


def derive_folded_value(node: vy_ast.VyperNode):
    if isinstance(node, vy_ast.BinOp):
        left = derive_folded_value(node.left)
        right = derive_folded_value(node.right)
        if left is None or right is None:
            return None
        return node.op._op(left, right)
    elif isinstance(node, vy_ast.BoolOp):
        values = [derive_folded_value(i) for i in node.values]
        if any(v is None for v in values):
            return None
        return node.op._op(values)
    elif isinstance(node, vy_ast.Call):
        # constant structs
        if len(node.args) == 1 and isinstance(node.args[0], vy_ast.Dict):
            return derive_folded_value(node.args[0])

        from vyper.semantics.analysis.utils import get_exact_type_from_node

        call_type = get_exact_type_from_node(node.func)
        # builtins
        if hasattr(call_type, "evaluate"):
            try:
                evaluated = call_type.evaluate(node)
                return evaluated.value
            except (UnfoldableNode, VyperException):
                pass
    elif isinstance(node, vy_ast.Compare):
        left = derive_folded_value(node.left)

        if isinstance(node.op, (vy_ast.In, vy_ast.NotIn)):
            right = [derive_folded_value(i) for i in node.right.elements]
            if left is None or any(v is None for v in right):
                return None
            return node.op._op(left, right)

        right = derive_folded_value(node.right)
        if left is None or right is None:
            return None
        return node.op._op(left, right)
    elif isinstance(node, vy_ast.Constant):
        return node.value
    elif isinstance(node, vy_ast.Dict):
        values = [derive_folded_value(v) for v in node.values]
        if any(v is None for v in values):
            return None
        return {k: v for (k, v) in zip(node.keys, values)}
    elif isinstance(node, (vy_ast.List, vy_ast.Tuple)):
        val = [derive_folded_value(e) for e in node.elements]
        if None in val:
            return None
        return val
    elif isinstance(node, vy_ast.Name):
        ns = get_namespace()
        return ns._constants.get(node.id, None)
    elif isinstance(node, vy_ast.UnaryOp):
        operand = derive_folded_value(node.operand)
        if operand is None:
            return None
        return node.op._op(operand)

    return None


def get_index_value(node: vy_ast.Index, constants: dict) -> int:
    """
    Return the literal value for a `Subscript` index.

    Arguments
    ---------
    node : vy_ast.Index
        Vyper ast node from the `slice` member of a Subscript node. Must be an
        `Index` object (Vyper does not support `Slice` or `ExtSlice`).

    Returns
    -------
    int
        Literal integer value.
    """
    # this is imported to improve error messages
    # TODO: revisit this!
    from vyper.semantics.analysis.utils import get_possible_types_from_node

    val = derive_folded_value(node.value)

    if not isinstance(val, int):
        if hasattr(node, "value"):
            # even though the subscript is an invalid type, first check if it's a valid _something_
            # this gives a more accurate error in case of e.g. a typo in a constant variable name
            try:
                get_possible_types_from_node(node.value)
            except StructureException:
                # StructureException is a very broad error, better to raise InvalidType in this case
                pass

        raise InvalidType("Subscript must be a literal integer", node)

    if val <= 0:
        raise ArrayIndexException("Subscript must be greater than 0", node)

    return val
