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
from vyper.semantics.types.bases import BaseTypeDefinition, DataLocation
from vyper.semantics.types.indexable.sequence import ArrayDefinition, TupleDefinition
from vyper.semantics.validation.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.validation.utils import get_exact_type_from_node, get_index_value


class StringEnum(enum.Enum):
    @staticmethod
    def auto():
        return enum.auto()

    # Must be first, or else won't work, specifies what .value is
    def _generate_next_value_(name, start, count, last_values):
        return name.lower()

    # Override ValueError with our own internal exception
    @classmethod
    def _missing_(cls, value):
        raise VyperInternalException(f"{value} is not a valid {cls.__name__}")

    @classmethod
    def is_valid_value(cls, value: str) -> bool:
        return value in set(o.value for o in cls)

    @classmethod
    def options(cls) -> List["StringEnum"]:
        return list(cls)

    @classmethod
    def values(cls) -> List[str]:
        return [v.value for v in cls.options()]

    # Comparison operations
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            raise CompilerPanic("Can only compare like types.")
        return self is other

    # Python normally does __ne__(other) ==> not self.__eq__(other)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            raise CompilerPanic("Can only compare like types.")
        options = self.__class__.options()
        return options.index(self) < options.index(other)  # type: ignore

    def __le__(self, other: object) -> bool:
        return self.__eq__(other) or self.__lt__(other)

    def __gt__(self, other: object) -> bool:
        return not self.__le__(other)

    def __ge__(self, other: object) -> bool:
        return self.__eq__(other) or self.__gt__(other)


def get_type_from_abi(
    abi_type: Dict,
    location: DataLocation = DataLocation.UNSET,
    is_constant: bool = False,
    is_public: bool = False,
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
            value_type = get_type_from_abi(
                {"type": value_type_string}, location=location, is_constant=is_constant
            )
        except UnknownType:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None
        try:
            return ArrayDefinition(
                value_type,
                length,
                location=location,
                is_constant=is_constant,
                is_public=is_public,
            )
        except InvalidType:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None

    else:
        try:
            return namespace[type_string]._type(
                location=location, is_constant=is_constant, is_public=is_public
            )
        except KeyError:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None


def get_type_from_annotation(
    node: vy_ast.VyperNode,
    location: DataLocation,
    is_constant: bool = False,
    is_public: bool = False,
    is_immutable: bool = False,
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
    except StopIteration:
        raise StructureException("Invalid syntax for type declaration", node)
    try:
        type_obj = namespace[type_name]
    except UndeclaredDefinition:
        suggestions_str = get_levenshtein_error_suggestions(type_name, namespace, 0.3)
        raise UnknownType(
            f"No builtin or user-defined type named '{type_name}'. {suggestions_str}",
            node,
        ) from None

    if getattr(type_obj, "_as_array", False) and isinstance(node, vy_ast.Subscript):
        # TODO: handle `is_immutable` for arrays
        # if type can be an array and node is a subscript, create an `ArrayDefinition`
        length = get_index_value(node.slice)
        value_type = get_type_from_annotation(
            node.value, location, is_constant, False, is_immutable
        )
        return ArrayDefinition(value_type, length, location, is_constant, is_public, is_immutable)

    try:
        return type_obj.from_annotation(node, location, is_constant, is_public, is_immutable)
    except AttributeError:
        raise InvalidType(f"'{type_name}' is not a valid type", node) from None


def _check_literal(node: vy_ast.VyperNode) -> bool:
    """
    Check if the given node is a literal value.
    """
    if isinstance(node, vy_ast.Constant):
        return True
    elif isinstance(node, (vy_ast.Tuple, vy_ast.List)):
        return all(_check_literal(item) for item in node.elements)
    return False


def check_constant(node: vy_ast.VyperNode) -> bool:
    """
    Check if the given node is a literal or constant value.
    """
    if _check_literal(node):
        return True
    if isinstance(node, (vy_ast.Tuple, vy_ast.List)):
        return all(check_constant(item) for item in node.elements)
    if isinstance(node, vy_ast.Call):
        args = node.args
        if len(args) == 1 and isinstance(args[0], vy_ast.Dict):
            return all(check_constant(v) for v in args[0].values)

    return False


def check_kwargable(node: vy_ast.VyperNode) -> bool:
    """
    Check if the given node can be used as a default arg
    """
    if _check_literal(node):
        return True
    if isinstance(node, (vy_ast.Tuple, vy_ast.List)):
        return all(check_kwargable(item) for item in node.elements)
    if isinstance(node, vy_ast.Call):
        args = node.args
        if len(args) == 1 and isinstance(args[0], vy_ast.Dict):
            return all(check_kwargable(v) for v in args[0].values)

    value_type = get_exact_type_from_node(node)
    # is_constant here actually means not_assignable, and is to be renamed
    return getattr(value_type, "is_constant", False)


def generate_abi_type(type_definition, name=""):
    # TODO oof fixme
    from vyper.semantics.types.user.struct import StructDefinition

    if isinstance(type_definition, StructDefinition):
        return {
            "name": name,
            "type": "tuple",
            "components": [generate_abi_type(v, k) for k, v in type_definition.members.items()],
        }
    if isinstance(type_definition, TupleDefinition):
        return {
            "type": "tuple",
            "components": [generate_abi_type(i) for i in type_definition.value_type],
        }
    return {"name": name, "type": type_definition.canonical_abi_type}
