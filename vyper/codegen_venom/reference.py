"""The obligations of a located value across later expression evaluation.

A projection keeps its evaluated indices, and a pointer-cell payload keeps the
cell and the address originally read from it. Copying a value into fresh memory
discharges these obligations; projecting or selecting a reference preserves them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import zip_longest
from typing import TYPE_CHECKING, Protocol

from vyper.semantics.data_locations import DataLocation
from vyper.venom.basicblock import IRBasicBlock, IRLiteral, IROperand, IRVariable

if TYPE_CHECKING:
    from vyper.venom.builder import VenomBuilder


class _ReferenceContext(Protocol):
    """The emission operations references need, independent of codegen context state."""

    builder: VenomBuilder

    def load_word(self, addr: IROperand, location: DataLocation) -> IROperand:
        raise NotImplementedError


@dataclass(frozen=True)
class ArrayIndex:
    array: IROperand
    index: IROperand
    location: DataLocation
    # A conditional may select a reference with fewer ancestor indices.
    active: IROperand | None = None


@dataclass(frozen=True)
class PayloadAnchor:
    cell: IROperand
    payload: IROperand
    # None means unconditional; otherwise this is the selected arm's flag.
    active: IROperand | None = None


@dataclass(frozen=True)
class ValueReference:
    anchor: PayloadAnchor | None = None
    indices: tuple[ArrayIndex, ...] = ()

    def project(self, array: IROperand, index: IROperand, location: DataLocation):
        return replace(self, indices=self.indices + (ArrayIndex(array, index, location),))

    def resolve(self, ctx: _ReferenceContext, ptr: IROperand) -> tuple[IROperand, ValueReference]:
        """Reload the selected payload and check indices without evaluating them again.

        All indices following an anchor are inside its payload. Dereferencing a
        cell in an array element starts a new reference: such payloads cannot be
        mutated through that element and remain valid independently of its frame.

        Write references acquired ownership before the later expression. Struct
        copies made by that expression do not outlive the pending write, so
        resolving its target does not acquire ownership a second time.
        """
        b = ctx.builder
        anchor = self.anchor
        delta = None
        if anchor is not None:
            assert isinstance(anchor.cell, IRVariable)
            payload = b.mload(anchor.cell)
            if anchor.active is not None:
                payload = b.select(anchor.active, payload, anchor.payload)
            delta = b.sub(payload, anchor.payload)
            ptr = b.add(ptr, delta)
            anchor = replace(anchor, payload=payload)

        indices = []
        for subscript in self.indices:
            array = subscript.array
            if delta is not None:
                assert subscript.location == DataLocation.MEMORY
                array = b.add(array, delta)
            if subscript.active is not None:
                array = b.select(subscript.active, array, IRLiteral(0))
            length = ctx.load_word(array, subscript.location)
            valid = b.lt(subscript.index, length)
            if subscript.active is not None:
                valid = b.or_(b.iszero(subscript.active), valid)
            b.assert_(valid)
            indices.append(replace(subscript, array=array))
        return ptr, ValueReference(anchor, tuple(indices))


def merge_references(
    ctx: _ReferenceContext,
    left: ValueReference | None,
    right: ValueReference | None,
    left_block: IRBasicBlock,
    right_block: IRBasicBlock,
) -> ValueReference | None:
    """Merge reference metadata on the same edges as a conditional's value.

    Missing obligations have a false flag and zero operands. Their unused mload
    reads scratch word zero, never an address belonging only to the other arm.
    """
    if left is None and right is None:
        return None
    if left is None:
        left = ValueReference()
    if right is None:
        right = ValueReference()

    def merge(a: IROperand, b: IROperand) -> IROperand:
        if a == b:
            return a
        result = ctx.builder.new_variable()
        left_block.append_instruction("assign", a, ret=result)
        right_block.append_instruction("assign", b, ret=result)
        return result

    def active(flag: IROperand | None) -> IROperand:
        return IRLiteral(1) if flag is None else flag

    def merge_active(a: IROperand | None, b: IROperand | None) -> IROperand | None:
        if a is None and b is None:
            return None
        return merge(active(a), active(b))

    anchor = None
    if left.anchor is not None or right.anchor is not None:
        missing = PayloadAnchor(IRLiteral(0), IRLiteral(0), IRLiteral(0))
        a = missing if left.anchor is None else left.anchor
        b = missing if right.anchor is None else right.anchor
        anchor = PayloadAnchor(
            merge(a.cell, b.cell), merge(a.payload, b.payload), merge_active(a.active, b.active)
        )

    indices = []
    missing_index = ArrayIndex(IRLiteral(0), IRLiteral(0), DataLocation.MEMORY, IRLiteral(0))
    for x, y in zip_longest(left.indices, right.indices, fillvalue=missing_index):
        # Conditional aggregate arms have been normalized to memory.
        assert x.location == y.location == DataLocation.MEMORY
        indices.append(
            ArrayIndex(
                merge(x.array, y.array),
                merge(x.index, y.index),
                DataLocation.MEMORY,
                merge_active(x.active, y.active),
            )
        )
    return ValueReference(anchor, tuple(indices))
