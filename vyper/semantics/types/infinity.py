import enum
from typing import Any, TypeAlias, TypeGuard


class Inf(enum.Enum):
    """Singleton representing unbounded length."""

    INF = "INF"

    def __repr__(self):
        return "INF"

    def __str__(self):
        return "INF"


INF = Inf.INF

# An unbounded (INF) value has no inline representation, so a struct member or
# a local of an INF type occupies a fixed-size cell holding its current payload
# pointer and capacity instead. See `VenomCodegenContext.store_pointer_cell`.
POINTER_CELL_SIZE = 64
POINTER_CELL_CAPACITY_OFFSET = 32


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


def is_supported_unbounded_struct_member(typ) -> bool:
    """Return True if a struct member may have type `typ`.

    An INF member has no inline representation, so it occupies a
    `POINTER_CELL_SIZE` cell holding a pointer to its payload (see
    `VenomCodegenContext.store_pointer_cell`). That keeps the struct's size a
    compile-time constant, but only for the shapes one cell can describe: a
    direct INF sequence of bounded elements, or another such struct inline.

    This is stricter than `type_contains_unrepresentable_unbounded_sequence`,
    which also accepts a DynArray of pointer-cell structs: that shape has a
    memory layout but no static ABI size bound, and a struct must stay
    encodable because it can be returned.
    """
    if not type_contains_unbounded_sequence(typ):
        return True

    if is_unbounded_bytestring_type(typ):
        return True

    if is_unbounded_dynarray_type(typ):
        # an INF element would need a cell of its own inside the payload
        return not type_contains_unbounded_sequence(typ.value_type)

    return is_supported_unbounded_struct_type(typ)


def is_supported_unbounded_struct_type(typ) -> bool:
    """Return True for structs whose INF members occupy pointer cells.

    Returns True for a struct with no INF member at all; callers pair it with
    `type_contains_unbounded_sequence`.
    """
    if getattr(typ, "typeclass", None) != "struct":
        return False

    return all(is_supported_unbounded_struct_member(t) for t in typ.members.values())


def type_contains_nested_unbounded_sequence(typ) -> bool:
    """Return True if `typ` contains INF below a direct top-level sequence.

    An INF DynArray of pointer-cell structs counts as nested: its elements
    have no static ABI size bound, so an encoding buffer for it cannot be
    sized from its length alone.
    """
    if not type_contains_unbounded_sequence(typ):
        return False

    if is_unbounded_dynarray_type(typ):
        # an INF element has no static per-element ABI size bound
        return type_contains_unbounded_sequence(typ.value_type)

    return not is_unbounded_sequence_type(typ)


def type_contains_unrepresentable_unbounded_sequence(typ) -> bool:
    """Return True if INF appears in `typ` where memory has no room for it.

    A value held in memory (an argument, a local, an internal call argument)
    can carry INF as the value itself (a runtime-sized buffer) or as a struct
    member (a pointer cell), including in the elements of a DynArray, whose
    stride stays a compile-time constant. Anywhere else the offsets after the
    INF value would be runtime values, which struct/tuple/array addressing
    cannot express.

    Having a memory layout does not make a type encodable; positions that
    encode use `type_contains_unsupported_unbounded_return` instead.
    """
    if not type_contains_unbounded_sequence(typ):
        return False

    if is_supported_unbounded_struct_type(typ):
        return False

    if getattr(typ, "typeclass", None) == "dynamic_array":
        return type_contains_unrepresentable_unbounded_sequence(typ.value_type)

    return not is_unbounded_sequence_type(typ)


def type_contains_unsupported_unbounded_sequence(typ) -> bool:
    """Return True if INF appears outside the supported top-level shapes."""
    return type_contains_unbounded_sequence(typ) and not (
        is_unbounded_sequence_type(typ) or is_supported_unbounded_tuple_type(typ)
    )


def type_contains_unsupported_unbounded_return(typ) -> bool:
    """Return True if a return of `typ` has no supported encoding.

    Accepts everything `type_contains_unsupported_unbounded_sequence` does,
    plus a struct with pointer-cell members. A DynArray of such structs stays
    rejected: sizing the return buffer would mean walking every element's
    cells, which the per-element bound used for INF DynArrays cannot do.
    """
    if not type_contains_unbounded_sequence(typ):
        return False

    if is_unbounded_dynarray_type(typ):
        return type_contains_unbounded_sequence(typ.value_type)

    if is_supported_unbounded_struct_type(typ):
        return False

    return type_contains_unsupported_unbounded_sequence(typ)


def length_to_json(length: LengthUpperBound) -> int | str:
    """Return a JSON-serializable representation of a length value."""
    if length is INF or length is WILDCARD:
        return str(length)
    return length


def member_slot_size(typ) -> int:
    """Return the bytes a struct member occupies inline in the struct."""
    if is_unbounded_sequence_type(typ):
        return POINTER_CELL_SIZE
    return typ.size_in_bytes


def unbounded_member_cells(struct_t) -> list[tuple[int, Any]]:
    """Return `(byte offset, member type)` for every pointer cell in a struct.

    Cells of nested structs are included at their offset in the outer struct.
    """
    cells = []
    offset = 0
    for member_t in struct_t.member_types.values():
        if is_unbounded_sequence_type(member_t):
            cells.append((offset, member_t))
        elif getattr(member_t, "typeclass", None) == "struct":
            cells.extend((offset + off, t) for off, t in unbounded_member_cells(member_t))
        offset += member_slot_size(member_t)
    return cells


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
