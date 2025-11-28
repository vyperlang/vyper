from vyper.ir.compile_ir import PUSH
from vyper.utils import MemoryPositions, OrderedSet
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand, IRVariable
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

    def __init__(self, ctx: IRContext, initial_offset: int | None = None):
        self.ctx = ctx
        self._spill_free_slots: list[int] = []
        self._spill_slot_offsets: dict[IRFunction, list[int]] = {}
        self._spill_insert_index: dict[IRFunction, int] = {}
        self._next_spill_offset = MemoryPositions.STACK_SPILL_BASE
        if initial_offset is not None:
            self._next_spill_offset = initial_offset
        self._next_spill_alloca_id = 0
        self._current_function: IRFunction | None = None

    def set_current_function(self, fn: IRFunction | None) -> None:
        """Set the current function being processed."""
        self._current_function = fn
        if fn is not None:
            self._prepare_spill_state(fn)

    def reset_spill_slots(self) -> None:
        self._spill_free_slots = []

    def _prepare_spill_state(self, fn: IRFunction) -> None:
        if fn in self._spill_slot_offsets:
            return

        entry = fn.entry
        insert_idx = 0
        for inst in entry.instructions:
            if inst.opcode == "param":
                insert_idx += 1
            else:
                break

        self._spill_slot_offsets[fn] = []
        self._spill_insert_index[fn] = insert_idx

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
        if swap_idx < 1:
            from vyper.exceptions import StackTooDeep

            raise StackTooDeep(f"Unsupported swap depth {swap_idx}")

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

    def dup(self, assembly: list, stack: StackModel, depth: int, dry_run: bool = False) -> None:
        """
        Dup operation that handles deep stacks via spilling.

        For stacks deeper than 16, spills the stack segment to memory,
        then restores it with duplication.
        """
        dup_idx = 1 - depth
        if dup_idx < 1:
            from vyper.exceptions import StackTooDeep

            raise StackTooDeep(f"Unsupported dup depth {dup_idx}")

        if dup_idx <= 16:
            stack.dup(depth)
            assembly.append(f"DUP{dup_idx}")
            return

        # For deep stacks, use spill/restore technique
        chunk_size = dup_idx
        spill_ops, offsets, _ = self._spill_stack_segment(assembly, stack, chunk_size, dry_run)

        indices = list(range(chunk_size))
        desired_indices = [indices[-1]] + indices

        self._restore_spilled_segment(assembly, stack, spill_ops, offsets, desired_indices, dry_run)

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

            offset = self._acquire_spill_offset(dry_run)
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
        if dry_run:
            return self._acquire_spill_offset(dry_run)
        if self._current_function is None:
            offset = self._next_spill_offset
            self._next_spill_offset += 32
            return offset
        return self._allocate_spill_slot(self._current_function)

    def _acquire_spill_offset(self, dry_run: bool) -> int:
        if self._spill_free_slots:
            return self._spill_free_slots.pop() if not dry_run else self._spill_free_slots[-1]
        return self._get_spill_slot(dry_run)

    def _allocate_spill_slot(self, fn: IRFunction) -> int:
        entry = fn.entry
        insert_idx = self._spill_insert_index[fn]

        offset = self._next_spill_offset
        self._next_spill_offset += 32

        offset_lit = IRLiteral(offset)
        size_lit = IRLiteral(32)
        id_lit = IRLiteral(self._next_spill_alloca_id)
        self._next_spill_alloca_id += 1

        output_var = fn.get_next_variable()

        inst = IRInstruction("alloca", [offset_lit, size_lit, id_lit], [output_var])
        entry.instructions.insert(insert_idx, inst)
        self._spill_insert_index[fn] += 1

        self._spill_slot_offsets[fn].append(offset)
        return offset
