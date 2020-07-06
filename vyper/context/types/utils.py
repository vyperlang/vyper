import enum
from typing import Dict, List

from vyper import ast as vy_ast
from vyper.context.namespace import get_namespace
from vyper.context.types.bases import BaseTypeDefinition, DataLocation
from vyper.context.types.indexable.sequence import ArrayDefinition
from vyper.context.validation.utils import (
    get_exact_type_from_node,
    get_index_value,
)
from vyper.exceptions import (
    CompilerPanic,
    InvalidType,
    StructureException,
    UndeclaredDefinition,
    UnknownType,
    VyperInternalException,
)


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
    is_immutable: bool = False,
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
                {"type": value_type_string}, location=location, is_immutable=is_immutable
            )
        except UnknownType:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None
        try:
            return ArrayDefinition(
                value_type,
                length,
                location=location,
                is_immutable=is_immutable,
                is_public=is_public,
            )
        except InvalidType:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None

    else:
        try:
            return namespace[type_string]._type(
                location=location, is_immutable=is_immutable, is_public=is_public
            )
        except KeyError:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None


def get_type_from_annotation(
    node: vy_ast.VyperNode,
    location: DataLocation,
    is_immutable: bool = False,
    is_public: bool = False,
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
        raise UnknownType(f"No builtin or user-defined type named '{type_name}'", node) from None

    if getattr(type_obj, "_as_array", False) and isinstance(node, vy_ast.Subscript):
        # if type can be an array and node is a subscript, create an `ArrayDefinition`
        length = get_index_value(node.slice)
        value_type = get_type_from_annotation(node.value, location, is_immutable, False)
        return ArrayDefinition(value_type, length, location, is_immutable, is_public)

    try:
        return type_obj.from_annotation(node, location, is_immutable, is_public)
    except AttributeError:
        raise InvalidType(f"'{type_name}' is not a valid type", node) from None


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
    return getattr(value_type, "is_immutable", False)
