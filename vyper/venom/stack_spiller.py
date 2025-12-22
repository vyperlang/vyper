from typing import Optional

from vyper.exceptions import CompilerPanic
from vyper.ir.compile_ir import PUSH
from vyper.utils import OrderedSet
from vyper.venom.basicblock import IROperand, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.stack_model import StackModel


class StackSpiller:
    """
    Manages stack spilling operations for deep stacks.
    - Spilling operands to memory
    - Restoring spilled operands from memory
    - Managing spill slot allocation and deallocation
    """

    def __init__(self, ctx: IRContext):
        self.ctx = ctx
        self._spill_free_slots: list[int] = []
        self._next_spill_offset: Optional[int] = None
        self._current_function: Optional[IRFunction] = None

    def set_current_function(self, fn: Optional[IRFunction]) -> None:
        """Set the current function being processed."""
        self._current_function = fn
        if fn is not None and fn in self.ctx.mem_allocator.fn_eom:
            self._next_spill_offset = self.ctx.mem_allocator.fn_eom[fn]

    def reset_spill_slots(self) -> None:
        self._spill_free_slots = []

    def snapshot(self):
        """Snapshot mutable state for dry-run isolation."""
        return (self._spill_free_slots.copy(), self._next_spill_offset)

    def restore(self, snap) -> None:
        """Restore from snapshot."""
        self._spill_free_slots, self._next_spill_offset = snap

    def spill_operand(
        self,
        assembly: list,
        stack: StackModel,
        spilled: dict[IROperand, int],
        depth: int,
        dry_run: bool = False,
    ) -> None:
        """Spill an operand from the stack to memory."""
        operand = stack.peek(depth)
        assert isinstance(operand, IRVariable), operand

        if depth != 0:
            self.swap(assembly, stack, depth, dry_run)

        offset = self._get_spill_slot(dry_run)
        assembly.extend(PUSH(offset))
        assembly.append("MSTORE")
        stack.pop()
        spilled[operand] = offset

    def restore_spilled_operand(
        self,
        assembly: list,
        stack: StackModel,
        spilled: dict[IROperand, int],
        op: IRVariable,
        dry_run: bool = False,
    ) -> None:
        """Restore a spilled operand from memory to the stack."""
        offset = spilled.pop(op)
        if not dry_run:
            self._spill_free_slots.append(offset)
        assembly.extend(PUSH(offset))
        assembly.append("MLOAD")
        stack.push(op)

    def release_dead_spills(
        self, spilled: dict[IROperand, int], live_set: OrderedSet[IRVariable]
    ) -> None:
        """Release memory slots for operands that are no longer live."""
        for op in list(spilled.keys()):
            if isinstance(op, IRVariable) and op in live_set:
                continue
            offset = spilled.pop(op)
            self._spill_free_slots.append(offset)

    def swap(self, assembly: list, stack: StackModel, depth: int, dry_run: bool = False) -> int:
        """
        Swap operation that handles deep stacks via spilling.

        For stacks deeper than 16, spills the stack segment to memory,
        then restores it in swapped order.
        """
        # Swaps of the top is no op
        if depth == 0:
            return 0

        swap_idx = -depth
        if swap_idx <= 16:
            stack.swap(depth)
            assembly.append(f"SWAP{swap_idx}")
            return 1

        # For deep stacks, use spill/restore technique
        chunk_size = swap_idx + 1
        spill_ops, offsets, cost = self._spill_stack_segment(assembly, stack, chunk_size, dry_run)

        indices = list(range(chunk_size))
        if chunk_size == 1:
            desired_indices = indices
        else:
            desired_indices = [indices[-1]] + indices[1:-1] + [indices[0]]

        cost += self._restore_spilled_segment(
            assembly, stack, spill_ops, offsets, desired_indices, dry_run
        )
        return cost

    def dup(self, assembly: list, stack: StackModel, depth: int, dry_run: bool = False) -> int:
        """
        Dup operation that handles deep stacks via spilling.

        For stacks deeper than 16, spills the stack segment to memory,
        then restores it with duplication.

        Returns the cost (number of operations emitted).
        """
        dup_idx = 1 - depth
        if dup_idx <= 16:
            stack.dup(depth)
            assembly.append(f"DUP{dup_idx}")
            return 1

        # For deep stacks, use spill/restore technique
        chunk_size = dup_idx
        spill_ops, offsets, cost = self._spill_stack_segment(assembly, stack, chunk_size, dry_run)

        indices = list(range(chunk_size))
        desired_indices = [indices[-1]] + indices

        cost += self._restore_spilled_segment(
            assembly, stack, spill_ops, offsets, desired_indices, dry_run
        )
        return cost

    def _spill_stack_segment(
        self, assembly: list, stack: StackModel, count: int, dry_run: bool
    ) -> tuple[list[IROperand], list[int], int]:
        """Spill a segment of the stack to memory."""
        spill_ops: list[IROperand] = []
        offsets: list[int] = []
        cost = 0

        for _ in range(count):
            op = stack.peek(0)
            spill_ops.append(op)

            offset = self._get_spill_slot(dry_run)
            offsets.append(offset)

            assembly.extend(PUSH(offset))
            assembly.append("MSTORE")
            stack.pop()
            cost += 2

        return spill_ops, offsets, cost

    def _restore_spilled_segment(
        self,
        assembly: list,
        stack: StackModel,
        spill_ops: list[IROperand],
        offsets: list[int],
        desired_indices: list[int],
        dry_run: bool,
    ) -> int:
        """Restore a spilled segment from memory to the stack."""
        cost = 0

        for idx in reversed(desired_indices):
            assembly.extend(PUSH(offsets[idx]))
            assembly.append("MLOAD")
            stack.push(spill_ops[idx])
            cost += 2

        if not dry_run:
            for offset in offsets:
                self._spill_free_slots.append(offset)

        return cost

    def _get_spill_slot(self, dry_run: bool) -> int:
        """Get a spill slot offset, reusing freed slots when available."""
        if len(self._spill_free_slots) > 0:
            if dry_run:
                return self._spill_free_slots[-1]
            return self._spill_free_slots.pop()
        # Allocate a new slot
        if self._next_spill_offset is None:
            fn = self._current_function
            assert fn is not None
            raise CompilerPanic(f"Function {fn.name} needs to spill but is not in fn_eom")
        offset = self._next_spill_offset
        if not dry_run:
            self._next_spill_offset += 32
        return offset
