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
    """Return True for tuples whose INF members are direct sequences of bounded elements.

    Such a tuple is built in the dynamic tuple frame
    (`VenomCodegenContext.is_dynamic_tuple_frame_type`), where every member
    is a 32-byte slot holding a payload pointer, so a member must itself be
    the sequence: a struct with INF members or an INF DynArray of such
    structs has no single payload to point at.
    """
    if getattr(typ, "typeclass", None) != "tuple":
        return False

    for member_t in typ.member_types:
        if not type_contains_unbounded_sequence(member_t):
            continue
        if not is_unbounded_sequence_type(member_t):
            return False
        # the frame moves a member as one block sized by its length word
        # (one `dret` pair, a `copy_sequence_to_scratch` byte copy), which
        # leaves payloads held by the elements behind, e.g. in the callee
        # frame of an internal return. The rule does not depend on the
        # function's visibility, so external tuple returns share it.
        if is_unbounded_dynarray_type(member_t) and type_contains_unbounded_sequence(
            member_t.value_type
        ):
            return False

    return True


def is_runtime_sizable_type(typ) -> bool:
    """Return True if a value of `typ` has a memory layout and a runtime encoded size.

    The ABI can encode any shape holding INF; what the compiler needs is a
    place in memory for every INF sequence and a way to size an encoding
    buffer from the value at hand. Both exist when every INF sequence sits
    at a compile-time offset from its container and holds bounded elements,
    so that its size follows from its length word: a bounded type
    (trivially), a direct `Bytes[INF]`, `String[INF]` or `DynArray[T, INF]`
    with bounded `T`, a struct whose INF members are such types, and a
    DynArray, bounded or INF, of such structs, also nested. An INF struct
    member occupies a `POINTER_CELL_SIZE` cell (see
    `VenomCodegenContext.store_pointer_cell`), which keeps the struct at a
    compile-time size and makes its encoded size the static head plus the
    members' runtime sizes; an array of such structs keeps a compile-time
    stride, and sizing it walks the elements.

    Rejected: a tuple with an INF member (its frame exists only as a return
    value, see `is_runtime_sizable_return_type`), and a static array or
    mapping holding INF.

    This is the rule for struct members, for every position that holds a
    value in memory (function arguments, locals, `abi_decode` outputs) and
    for every position that encodes one (external call arguments, event
    and error members, `abi_encode`, `print`, `create_*` constructor
    arguments and `empty`).
    """
    if not type_contains_unbounded_sequence(typ):
        return True

    if is_unbounded_bytestring_type(typ):
        return True

    if getattr(typ, "typeclass", None) == "dynamic_array":
        elem_t = typ.value_type
        if not type_contains_unbounded_sequence(elem_t):
            return True
        return is_pointer_cell_struct_type(elem_t)

    if getattr(typ, "typeclass", None) == "struct":
        return all(is_runtime_sizable_type(t) for t in typ.members.values())

    return False


def is_pointer_cell_struct_type(typ) -> bool:
    """Return True for a struct with INF members, each held in a pointer cell."""
    if getattr(typ, "typeclass", None) != "struct":
        return False

    return type_contains_unbounded_sequence(typ) and is_runtime_sizable_type(typ)


def contains_pointer_cell_array(typ) -> bool:
    """Return True if a DynArray whose elements hold INF appears anywhere in `typ`.

    Such an array reaches one payload per element and cell, a runtime
    number, so an internal function returns a value holding one as a single
    packed buffer (`codegen_venom/packed_return.py`) instead of one `dret`
    pair per payload. Answers for every type, looking through static
    arrays, tuples and structs.
    """
    typeclass = getattr(typ, "typeclass", None)

    if typeclass == "dynamic_array":
        return type_contains_unbounded_sequence(typ.value_type)

    if typeclass == "static_array":
        return contains_pointer_cell_array(typ.value_type)

    if typeclass == "tuple":
        return any(contains_pointer_cell_array(t) for t in typ.member_types)

    if typeclass == "struct":
        return any(contains_pointer_cell_array(t) for t in typ.members.values())

    return False


def is_runtime_sizable_return_type(typ) -> bool:
    """Return True if a return value of `typ` can be sized at runtime.

    Everything `is_runtime_sizable_type` accepts, plus a tuple whose INF
    members are direct sequences: a return value is built in the dynamic
    tuple frame, which a memory value of the same tuple type does not have,
    so arguments and locals of that type stay rejected.
    """
    if is_supported_unbounded_tuple_type(typ):
        return True

    return is_runtime_sizable_type(typ)


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


def member_slot_size(typ) -> int:
    """Return the bytes a struct member occupies inline in the struct."""
    if is_unbounded_sequence_type(typ):
        return POINTER_CELL_SIZE
    return typ.size_in_bytes


def struct_member_offsets(struct_t) -> list[tuple[str, int, Any]]:
    """Return `(name, byte offset, member type)` for every member of a struct
    in memory, where an unbounded member takes a pointer cell."""
    ret = []
    offset = 0
    for name, member_t in struct_t.member_types.items():
        ret.append((name, offset, member_t))
        offset += member_slot_size(member_t)
    return ret


def unbounded_member_cells(struct_t) -> list[tuple[int, Any]]:
    """Return `(byte offset, member type)` for every pointer cell in a struct.

    Cells of nested structs are included at their offset in the outer struct.
    """
    cells = []
    for _, offset, member_t in struct_member_offsets(struct_t):
        if is_unbounded_sequence_type(member_t):
            cells.append((offset, member_t))
        elif getattr(member_t, "typeclass", None) == "struct":
            cells.extend((offset + off, t) for off, t in unbounded_member_cells(member_t))
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
