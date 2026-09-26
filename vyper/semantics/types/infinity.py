import enum
from typing import TypeAlias, TypeGuard


class Inf(enum.Enum):
    """Singleton representing unbounded length."""

    INF = "INF"

    def __repr__(self):
        return "INF"

    def __str__(self):
        return "INF"


INF = Inf.INF


class Wildcard(enum.Enum):
    """Singleton representing a wildcard length (matches any length)."""

    WILDCARD = "..."

    def __repr__(self):
        return "..."

    def __str__(self):
        return "..."


WILDCARD = Wildcard.WILDCARD

LengthUpperBound: TypeAlias = int | Inf | Wildcard


def is_bounded_length(_lengthval: LengthUpperBound) -> TypeGuard[int]:
    """Return True if val is a concrete int (not INF or WILDCARD)."""
    return _lengthval is not INF and _lengthval is not WILDCARD


def is_unbounded_bytestring_type(typ) -> bool:
    """Return True if `typ` is a Bytes/String with INF length."""
    return getattr(typ, "_is_bytestring", False) and getattr(typ, "length", None) is INF


def is_unbounded_dynarray_type(typ) -> bool:
    """Return True if `typ` is a DynArray with INF length."""
    return (
        getattr(typ, "typeclass", None) == "dynamic_array" and getattr(typ, "length", None) is INF
    )


def is_unbounded_sequence_type(typ) -> bool:
    """Return True if `typ` is a direct Bytes/String/DynArray with INF length."""
    return is_unbounded_bytestring_type(typ) or is_unbounded_dynarray_type(typ)


def is_supported_unbounded_tuple_type(typ) -> bool:
    """Return True for tuples whose INF members are direct top-level sequences."""
    if getattr(typ, "typeclass", None) != "tuple":
        return False

    for member_t in typ.member_types:
        if type_contains_nested_unbounded_sequence(member_t):
            return False

    return True


def type_contains_nested_unbounded_sequence(typ) -> bool:
    """Return True if `typ` contains INF below a direct top-level sequence."""
    return type_contains_unbounded_sequence(typ) and not is_unbounded_sequence_type(typ)


def type_contains_unsupported_unbounded_sequence(typ) -> bool:
    """Return True if INF appears outside the supported top-level shapes."""
    return type_contains_unbounded_sequence(typ) and not (
        is_unbounded_sequence_type(typ) or is_supported_unbounded_tuple_type(typ)
    )


def length_to_json(length: LengthUpperBound) -> int | str:
    """Return a JSON-serializable representation of a length value."""
    if length is INF or length is WILDCARD:
        return str(length)
    return length


def type_contains_unbounded_sequence(typ) -> bool:
    """Return True if `typ` is or contains a Bytes/String/DynArray with INF length."""
    if getattr(typ, "_is_bytestring", False):
        return getattr(typ, "length", None) is INF

    typeclass = getattr(typ, "typeclass", None)

    if typeclass == "dynamic_array":
        return getattr(typ, "length", None) is INF or type_contains_unbounded_sequence(
            typ.value_type
        )

    if typeclass == "static_array":
        return type_contains_unbounded_sequence(typ.value_type)

    if typeclass == "hashmap":
        return type_contains_unbounded_sequence(typ.key_type) or type_contains_unbounded_sequence(
            typ.value_type
        )

    if typeclass == "tuple":
        return any(type_contains_unbounded_sequence(t) for t in typ.member_types)

    if typeclass in ("struct", "error", "event"):
        return any(type_contains_unbounded_sequence(t) for t in typ.members.values())

    return False
