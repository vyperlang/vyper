from __future__ import annotations

import vyper.evm.address_space as addr_space
from vyper.utils import GAS_COPY_WORD
from vyper.venom.analysis import BasePtrAnalysis, DFGAnalysis, MemoryAliasAnalysis
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import Allocation


class CopyForwardingPolicy:
    """
    Shared copy-forwarding helpers for mcopy propagation and invoke copy forwarding.
    """

    MCOPY_BASE_COST: int = 3
    # Code deposit is 200 gas/byte, and eliding an mcopy removes at least
    # the one-byte MCOPY opcode from deployed bytecode.
    CODE_DEPOSIT_GAS_PER_BYTE: int = 200
    MIN_ELIDED_MCOPY_BYTES: int = 1

    function: IRFunction
    dfg: DFGAnalysis
    base_ptr: BasePtrAnalysis
    mem_alias: MemoryAliasAnalysis

    def __init__(
        self,
        function: IRFunction,
        dfg: DFGAnalysis,
        base_ptr: BasePtrAnalysis,
        mem_alias: MemoryAliasAnalysis,
    ):
        self.function = function
        self.dfg = dfg
        self.base_ptr = base_ptr
        self.mem_alias = mem_alias

    def copy_size(self, copy_inst: IRInstruction) -> int | None:
        size = copy_inst.operands[0]
        if isinstance(size, IRLiteral):
            return size.value
        return None

    def copy_source(self, copy_inst: IRInstruction) -> IROperand:
        _, src, _ = copy_inst.operands
        if isinstance(src, IRVariable):
            return self.dfg._traverse_assign_chain(src)
        return src

    def copy_destination_alloca(self, copy_inst: IRInstruction) -> Allocation | None:
        dst = copy_inst.operands[2]
        if not isinstance(dst, IRVariable):
            return None
        ptr = self.base_ptr.ptr_from_op(dst)
        if ptr is None:
            return None
        return ptr.base_alloca

    def copies_equivalent(self, inst1: IRInstruction, inst2: IRInstruction) -> bool:
        write_loc1 = self.base_ptr.get_write_location(inst1, addr_space.MEMORY)
        write_loc2 = self.base_ptr.get_write_location(inst2, addr_space.MEMORY)
        assert write_loc1 == write_loc2

        if inst1 is inst2:
            return True

        if inst1.opcode != inst2.opcode:
            return False

        size1, src_op1, _ = inst1.operands
        size2, src_op2, _ = inst2.operands

        return self.dfg.are_equivalent(src_op1, src_op2) and self.dfg.are_equivalent(size1, size2)

    def should_block_forwarding(
        self,
        copy_inst: IRInstruction,
        rewrite_sites: set[tuple[IRInstruction, int]],
        dst_alloca: Allocation,
    ) -> bool:
        src_alloca = self._copy_source_alloca(copy_inst)
        if src_alloca is None:
            return False

        if not self._alloca_has_memory_accesses_that_can_skip_copy(src_alloca, copy_inst):
            return False

        size = self.copy_size(copy_inst)
        if size is None:
            size = dst_alloca.alloca_size

        for invoke_inst, _ in rewrite_sites:
            high_addr = self._lowest_position_across_callee_frame(invoke_inst, size)
            if high_addr is None:
                continue
            penalty = self._memory_cost(high_addr + size) - self._memory_cost(size)
            if penalty > self._minimum_forwarding_savings(size):
                return True

        return False

    def _copy_source_alloca(self, copy_inst: IRInstruction) -> Allocation | None:
        src = copy_inst.operands[1]
        if not isinstance(src, IRVariable):
            return None
        ptr = self.base_ptr.ptr_from_op(src)
        if ptr is None:
            return None
        return ptr.base_alloca

    def _alloca_has_memory_accesses_that_can_skip_copy(
        self, alloca: Allocation, copy_inst: IRInstruction
    ) -> bool:
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst is copy_inst:
                    continue

                read_loc = self.base_ptr.get_read_location(inst, addr_space.MEMORY)
                if read_loc.alloca == alloca and self._access_can_skip_copy(inst, copy_inst):
                    return True

                write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)
                if write_loc.alloca == alloca and self._access_can_skip_copy(inst, copy_inst):
                    return True

        return False

    def _access_can_skip_copy(self, access_inst: IRInstruction, copy_inst: IRInstruction) -> bool:
        access_bb = access_inst.parent
        copy_bb = copy_inst.parent

        if access_bb is copy_bb:
            return False

        successors = list(self._successors(access_bb))
        if len(successors) == 0:
            return True

        worklist = successors
        visited: set[IRBasicBlock] = set()

        while len(worklist) > 0:
            bb = worklist.pop()
            if bb in visited:
                continue
            visited.add(bb)

            if bb is copy_bb:
                continue

            successors = list(self._successors(bb))
            if len(successors) == 0:
                return True

            worklist.extend(successors)

        return False

    def _successors(self, bb: IRBasicBlock) -> list[IRBasicBlock]:
        if not bb.is_terminated:
            return []
        return bb.out_bbs

    def _lowest_position_across_callee_frame(
        self, invoke_inst: IRInstruction, size: int
    ) -> int | None:
        callee = self._get_invoke_callee(invoke_inst)
        if callee is None:
            return None

        reserved = self._callee_reserved_intervals(callee)
        if len(reserved) == 0:
            return None

        ptr = 0
        for resv_ptr, resv_size in sorted(reserved):
            resv_end = resv_ptr + resv_size
            if resv_end <= ptr:
                continue
            if resv_ptr >= ptr + size:
                break
            ptr = resv_end

        return ptr

    def _callee_reserved_intervals(self, callee: IRFunction) -> list[tuple[int, int]]:
        allocator = self.function.ctx.mem_allocator
        if callee in allocator.mems_used:
            return [
                (allocator.allocated[alloca], alloca.alloca_size)
                for alloca in allocator.mems_used[callee]
                if alloca in allocator.allocated
            ]

        intervals: list[tuple[int, int]] = []
        ptr = 0
        for bb in callee.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "alloca":
                    continue
                size = inst.operands[0]
                if not isinstance(size, IRLiteral):
                    continue
                intervals.append((ptr, size.value))
                ptr += size.value

        return intervals

    def _get_invoke_callee(self, invoke_inst: IRInstruction) -> IRFunction | None:
        target = invoke_inst.operands[0]
        if not isinstance(target, IRLabel):
            return None
        return self.function.ctx.functions.get(target)

    def _memory_cost(self, size: int) -> int:
        words = (size + 31) // 32
        return 3 * words + words * words // 512

    def _mcopy_cost(self, size: int) -> int:
        words = (size + 31) // 32
        return self.MCOPY_BASE_COST + GAS_COPY_WORD * words

    def _minimum_forwarding_savings(self, size: int) -> int:
        return self._mcopy_cost(size) + (
            self.CODE_DEPOSIT_GAS_PER_BYTE * self.MIN_ELIDED_MCOPY_BYTES
        )
