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

    if typeclass in ("static_array", "hashmap"):
        return type_contains_unbounded_sequence(typ.value_type)

    if typeclass == "tuple":
        return any(type_contains_unbounded_sequence(t) for t in typ.member_types)

    if typeclass in ("struct", "error", "event"):
        return any(type_contains_unbounded_sequence(t) for t in typ.members.values())

    return False


def is_unbounded_sequence_root(typ) -> bool:
    if getattr(typ, "_is_bytestring", False):
        return getattr(typ, "length", None) is INF

    return (
        getattr(typ, "typeclass", None) == "dynamic_array" and getattr(typ, "length", None) is INF
    )
