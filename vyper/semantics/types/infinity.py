from __future__ import annotations

import enum
from typing import TYPE_CHECKING, TypeAlias, TypeGuard

if TYPE_CHECKING:
    from vyper.semantics.types.base import VyperType
    from vyper.semantics.types.bytestrings import _BytestringT
    from vyper.semantics.types.subscriptable import DArrayT
    from vyper.semantics.types.user import StructT

# Concrete type imports stay local: those modules import INF while defining
# their types.


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


def is_unbounded_bytestring_type(typ: VyperType | None) -> TypeGuard[_BytestringT]:
    """Return True if `typ` is a Bytes/String with INF length."""
    from vyper.semantics.types.bytestrings import _BytestringT

    return isinstance(typ, _BytestringT) and typ.length is INF


def is_unbounded_dynarray_type(typ: VyperType | None) -> TypeGuard[DArrayT]:
    """Return True if `typ` is a DynArray with INF length."""
    from vyper.semantics.types.subscriptable import DArrayT

    return isinstance(typ, DArrayT) and typ.length is INF


def is_unbounded_sequence_type(typ: VyperType | None) -> TypeGuard[_BytestringT | DArrayT]:
    """Return True if `typ` is a direct Bytes/String/DynArray with INF length."""
    return is_unbounded_bytestring_type(typ) or is_unbounded_dynarray_type(typ)


def is_supported_unbounded_tuple_type(typ: VyperType) -> bool:
    """Return True for tuples whose INF members are direct sequences of bounded elements.

    Such a tuple is built in the dynamic tuple frame
    (`VenomCodegenContext.is_dynamic_tuple_frame_type`), where every member
    is a 32-byte slot holding a payload pointer, so a member must itself be
    the sequence: a struct with INF members or an INF DynArray of such
    structs has no single payload to point at.
    """
    from vyper.semantics.types.subscriptable import TupleT

    if not isinstance(typ, TupleT):
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


def is_runtime_sizable_type(typ: VyperType) -> bool:
    """Return True if a value of `typ` has a memory layout and a runtime encoded size.

    The ABI can encode any shape holding INF; what the compiler needs is a
    place in memory for every INF sequence and a way to size an encoding
    buffer from the value at hand. Both exist when every INF sequence sits
    at a compile-time offset from its container and holds bounded elements,
    so that its size follows from its length word: a bounded type
    (trivially), a direct `Bytes[INF]`, `String[INF]` or `DynArray[T, INF]`
    with a fixed-size `T` (bounded, or a struct as below, but not an INF
    sequence), a struct whose INF members are such types, and a
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
    from vyper.semantics.types.subscriptable import DArrayT
    from vyper.semantics.types.user import StructT

    if not type_contains_unbounded_sequence(typ):
        return True

    if is_unbounded_bytestring_type(typ):
        return True

    if isinstance(typ, DArrayT):
        elem_t = typ.value_type
        if not type_contains_unbounded_sequence(elem_t):
            return True
        return is_pointer_cell_struct_type(elem_t)

    if isinstance(typ, StructT):
        return all(is_runtime_sizable_type(t) for t in typ.members.values())

    return False


def is_pointer_cell_struct_type(typ: VyperType | None) -> TypeGuard[StructT]:
    """Return True for a struct with INF members, each held in a pointer cell."""
    from vyper.semantics.types.user import StructT

    if not isinstance(typ, StructT):
        return False

    return type_contains_unbounded_sequence(typ) and is_runtime_sizable_type(typ)


def is_runtime_sizable_return_type(typ: VyperType) -> bool:
    """Return True if a return value of `typ` can be sized at runtime.

    Everything `is_runtime_sizable_type` accepts, plus a tuple whose INF
    members are direct sequences: a return value is built in the dynamic
    tuple frame, which a memory value of the same tuple type does not have,
    so arguments and locals of that type stay rejected.
    """
    if is_supported_unbounded_tuple_type(typ):
        return True

    return is_runtime_sizable_type(typ)


def is_unsupported_constant_type(typ: VyperType) -> bool:
    """Return True if a constant cannot have type `typ`.

    Constants hold INF only as a top-level sequence of elements without INF,
    or a tuple of such sequences; a struct with INF members is never part of
    a constant, including as the element of an INF DynArray.
    """
    if not type_contains_unbounded_sequence(typ):
        return False
    if is_supported_unbounded_tuple_type(typ):
        return False
    if is_unbounded_dynarray_type(typ):
        return type_contains_unbounded_sequence(typ.value_type)
    return not is_unbounded_sequence_type(typ)


def length_to_json(length: LengthUpperBound) -> int | str:
    """Return a JSON-serializable representation of a length value."""
    if length is INF or length is WILDCARD:
        return str(length)
    return length


def member_slot_size(typ: VyperType) -> int:
    """Return the bytes a struct member occupies inline in the struct."""
    if is_unbounded_sequence_type(typ):
        return POINTER_CELL_SIZE
    return typ.size_in_bytes


def struct_member_offsets(struct_t: StructT) -> list[tuple[str, int, VyperType]]:
    """Return `(name, byte offset, member type)` for every member of a struct
    in memory, where an unbounded member takes a pointer cell."""
    ret = []
    offset = 0
    for name, member_t in struct_t.member_types.items():
        ret.append((name, offset, member_t))
        offset += member_slot_size(member_t)
    return ret


def unbounded_member_cells(struct_t: StructT) -> list[tuple[int, VyperType]]:
    """Return `(byte offset, member type)` for every pointer cell at a static
    offset in a struct.

    Cells of nested structs are included at their offset in the outer struct;
    cells inside the elements of an array member are not.
    """
    from vyper.semantics.types.user import StructT

    cells: list[tuple[int, VyperType]] = []
    for _, offset, member_t in struct_member_offsets(struct_t):
        if is_unbounded_sequence_type(member_t):
            cells.append((offset, member_t))
        elif isinstance(member_t, StructT):
            cells.extend((offset + off, t) for off, t in unbounded_member_cells(member_t))
    return cells


def type_contains_unbounded_sequence(typ: VyperType) -> bool:
    """Return True if `typ` is or contains a Bytes/String/DynArray with INF length."""
    from vyper.semantics.types.bytestrings import _BytestringT
    from vyper.semantics.types.subscriptable import DArrayT, HashMapT, SArrayT, TupleT
    from vyper.semantics.types.user import ErrorT, EventT, StructT

    if isinstance(typ, _BytestringT):
        return typ.length is INF

    if isinstance(typ, DArrayT):
        return typ.length is INF or type_contains_unbounded_sequence(typ.value_type)

    if isinstance(typ, SArrayT):
        return type_contains_unbounded_sequence(typ.value_type)

    if isinstance(typ, HashMapT):
        return type_contains_unbounded_sequence(typ.key_type) or type_contains_unbounded_sequence(
            typ.value_type
        )

    if isinstance(typ, TupleT):
        return any(type_contains_unbounded_sequence(t) for t in typ.member_types)

    if isinstance(typ, (StructT, ErrorT, EventT)):
        return any(type_contains_unbounded_sequence(t) for t in typ.members.values())

    return False
