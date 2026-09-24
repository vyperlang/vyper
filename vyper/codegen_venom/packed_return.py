"""
Packing of internal return values that hold an array of pointer-cell structs.

`dret` keeps a returned buffer alive by moving a compile-time number of
(src, size) pairs into the caller's frame. An array whose elements hold
pointer cells reaches one payload per element and cell, a runtime number, so
such a value is returned as a single pair instead: the callee copies the value
and every payload reachable from it into one buffer, writing each cell's
pointer as an offset from the start of the buffer, and the caller adds the
address the buffer landed at. Offsets make the buffer position-independent,
so the callee does not depend on where `dret` places it.

Every relocated cell has capacity 0 and its payload holds exactly its length:
the packed buffer has no spare room.

Sizes are not checked for overflow: every payload measured here is a live
buffer that was allocated with a checked size, so each summand is below the
memory limit, and every summand costs a loop iteration, so their number is
bounded by the gas limit; the sum stays far below 2**256.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from vyper.semantics.types import (
    DArrayT,
    StructT,
    VyperType,
    is_unbounded_bytestring_type,
    is_unbounded_dynarray_type,
    is_unbounded_sequence_type,
    member_slot_size,
    type_contains_unbounded_sequence,
)
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

if TYPE_CHECKING:
    from .context import VenomCodegenContext


def _for_each_cell(
    ctx: VenomCodegenContext,
    ptr: IRVariable,
    typ: VyperType,
    visit: Callable[[IRVariable, VyperType], None],
) -> None:
    """Call `visit(cell, member_t)` for every pointer cell held in the value at `ptr`.

    The value itself is walked: struct members and array elements, not the
    payloads the cells point to (`visit` recurses into those if it needs to).
    """
    b = ctx.builder

    if isinstance(typ, StructT):
        offset = 0
        for member_t in typ.member_types.values():
            if type_contains_unbounded_sequence(member_t):
                member_ptr = b.add(ptr, IRLiteral(offset))
                assert isinstance(member_ptr, IRVariable)
                if is_unbounded_sequence_type(member_t):
                    visit(member_ptr, member_t)
                else:
                    _for_each_cell(ctx, member_ptr, member_t, visit)
            offset += member_slot_size(member_t)
        return

    if isinstance(typ, DArrayT):
        elem_t = typ.value_type
        if not type_contains_unbounded_sequence(elem_t):
            return
        # `is_runtime_sizable_type`: INF-bearing elements are pointer-cell structs
        assert isinstance(elem_t, StructT)
        length = b.mload(ptr)
        data = b.add(ptr, IRLiteral(32))

        def visit_element(counter: IRVariable) -> None:
            elem_ptr = b.add(data, b.mul(counter, IRLiteral(elem_t.memory_bytes_required)))
            _for_each_cell(ctx, elem_ptr, elem_t, visit)

        ctx.emit_counted_loop(length, visit_element, "cell_walk")
        return

    # bytestrings and bounded values hold no cells
    assert is_unbounded_bytestring_type(typ) or not type_contains_unbounded_sequence(typ)


def _payload_size(ctx: VenomCodegenContext, payload: IRVariable, typ: VyperType) -> IROperand:
    """Return the memory size of the INF sequence at `payload`, a multiple of 32."""
    if is_unbounded_bytestring_type(typ):
        return ctx.unchecked_bytestring_runtime_size(payload)
    assert isinstance(typ, DArrayT) and is_unbounded_dynarray_type(typ)
    return ctx.unchecked_dynarray_runtime_size(payload, typ)


def _inline_size(ctx: VenomCodegenContext, ptr: IRVariable, typ: VyperType) -> IROperand:
    """Return the bytes the packed buffer reserves for the value itself.

    An array takes its runtime size, bounded or not: every reader of an
    array stops at its length, and the caller copies a bounded array by
    length. Anything else takes its full static size: the caller's view of a
    struct spans every member, including the unused tail of a bounded array
    member.
    """
    if isinstance(typ, DArrayT):
        return ctx.unchecked_dynarray_runtime_size(ptr, typ)
    return IRLiteral(typ.memory_bytes_required)


def pack_value_with_payloads(
    ctx: VenomCodegenContext, ptr: IRVariable, typ: VyperType
) -> tuple[IRVariable, IROperand]:
    """Copy the value at `ptr` and all payloads it reaches into one fresh buffer.

    Returns `(buffer, size)`. The value sits at the start of the buffer and
    every cell in the buffer holds `(payload offset from the buffer, 0)`;
    `rebase_packed_value` turns the offsets back into pointers.
    """
    b = ctx.builder

    inline_size = _inline_size(ctx, ptr, typ)
    total = b.assign(inline_size)

    def add_payload_size(cell: IRVariable, member_t: VyperType) -> None:
        payload = b.mload(cell)
        assert isinstance(payload, IRVariable)
        b.assign_to(b.add(total, _payload_size(ctx, payload, member_t)), total)
        _for_each_cell(ctx, payload, member_t, add_payload_size)

    _for_each_cell(ctx, ptr, typ, add_payload_size)

    buf = ctx.allocate_scratch(total)
    ctx.copy_memory_dynamic(buf, ptr, inline_size)
    cursor = b.assign(b.add(buf, inline_size))

    # the cells of the copies still hold the source pointers; each one is
    # read, its payload copied to the cursor, then the cell rewritten
    def relocate(cell: IRVariable, member_t: VyperType) -> None:
        payload = b.mload(cell)
        assert isinstance(payload, IRVariable)
        dst = b.assign(cursor)
        size = _payload_size(ctx, payload, member_t)
        ctx.copy_memory_dynamic(dst, payload, size)
        ctx.store_pointer_cell(cell, b.sub(dst, buf), IRLiteral(0))
        b.assign_to(b.add(dst, size), cursor)
        _for_each_cell(ctx, dst, member_t, relocate)

    _for_each_cell(ctx, buf, typ, relocate)

    return buf, total


def rebase_packed_value(ctx: VenomCodegenContext, buf: IRVariable, typ: VyperType) -> None:
    """Turn the cell offsets of a value packed by `pack_value_with_payloads` into pointers."""
    b = ctx.builder

    def rebase(cell: IRVariable, member_t: VyperType) -> None:
        payload = b.add(buf, b.mload(cell))
        assert isinstance(payload, IRVariable)
        # capacity is already 0 from the pack; only the pointer word changes
        b.mstore(cell, payload)
        _for_each_cell(ctx, payload, member_t, rebase)

    _for_each_cell(ctx, buf, typ, rebase)
