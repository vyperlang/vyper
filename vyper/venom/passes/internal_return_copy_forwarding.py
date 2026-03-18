from __future__ import annotations

import vyper.evm.address_space as addr_space
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.effects import EMPTY, Effects
from vyper.venom.memory_location import MemoryLocation
from vyper.venom.passes.invoke_copy_forwarding_common import InvokeCopyForwardingBase


class InternalReturnCopyForwardingPass(InvokeCopyForwardingBase):
    """
    Forward copies of internal call memory return buffers:

      invoke @callee_returning_memory, %ret_buf, ...
      mcopy %dst, %ret_buf, ...

    When `%ret_buf` has the expected constrained use-shape, rewrite `%dst`
    uses to `%ret_buf` and remove the copy.
    """

    def run_pass(self):
        self._prepare()
        changed = False

        for bb in self.function.get_basic_blocks():
            for inst in list(bb.instructions):
                if inst.opcode != "mcopy":
                    continue
                changed |= self._try_forward_internal_return_copy(inst)

        self._finish(changed)

    def _try_forward_internal_return_copy(self, copy_inst: IRInstruction) -> bool:
        dst = copy_inst.operands[2]
        src = copy_inst.operands[1]
        size = copy_inst.operands[0]
        if not isinstance(dst, IRVariable) or not isinstance(src, IRVariable):
            return False
        if not isinstance(size, IRLiteral):
            return False

        dst_root = self._assign_root_var(dst)
        src_root = self._assign_root_var(src)
        if dst_root == src_root:
            return False

        dst_root_inst = self.dfg.get_producing_instruction(dst_root)
        src_root_inst = self.dfg.get_producing_instruction(src_root)

        if not self._is_alloca_like(dst_root_inst) or not self._is_alloca_like(src_root_inst):
            return False
        assert dst_root_inst is not None and src_root_inst is not None  # ensured above
        if not self._matches_alloca_size(dst_root_inst, size.value):
            return False
        if not self._matches_alloca_size(src_root_inst, size.value):
            return False

        if not self._is_internal_return_buffer_source(src_root, copy_inst):
            return False

        dst_aliases = self._collect_assign_aliases(dst_root)
        rewrite_insts: set[IRInstruction] = set()

        for _, use, pos in self._iter_alias_use_positions(dst_aliases):
            if self._is_assign_output_use(use, pos):
                continue
            if use.opcode == "mcopy" and pos == 2 and use is copy_inst:
                continue
            if use.opcode == "phi":
                return False
            if use.parent is not copy_inst.parent:
                return False
            if not self._is_after(copy_inst, use):
                return False
            rewrite_insts.add(use)

        # Verify no memory-clobbering instruction between the mcopy and
        # the last rewritten use.  The invoke that fills %ret_buf is
        # validated by _is_internal_return_buffer_source (same BB,
        # before the mcopy), so we only scan from the mcopy onward.
        bb_insts = copy_inst.parent.instructions
        copy_idx = bb_insts.index(copy_inst)
        if rewrite_insts:
            last_use_idx = max(bb_insts.index(u) for u in rewrite_insts)
            src_loc = self.base_ptr.get_read_location(copy_inst, addr_space.MEMORY)
            if src_loc.is_empty():
                return False
            for inst in bb_insts[copy_idx + 1 : last_use_idx]:
                if inst.opcode == "invoke":
                    if self._invoke_may_clobber_src(inst, src_loc):
                        return False
                    continue

                if inst.get_write_effects() & Effects.MEMORY == EMPTY:
                    continue
                write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)
                if self.mem_alias.may_alias(src_loc, write_loc):
                    return False

        replace_map: dict[IROperand, IROperand] = {var: src_root for var in dst_aliases}
        for use in rewrite_insts:
            self.updater.update_operands(use, replace_map)

        self.updater.nop(copy_inst)
        return True

    def _is_internal_return_buffer_source(
        self, src_root: IRVariable, copy_inst: IRInstruction
    ) -> bool:
        aliases = self._collect_assign_aliases(src_root)
        copy_seen = False
        invoke_sites: set[IRInstruction] = set()

        copy_bb = copy_inst.parent
        bb_insts = copy_bb.instructions
        copy_idx = bb_insts.index(copy_inst)

        for _, use, pos in self._iter_alias_use_positions(aliases):
            if self._is_assign_output_use(use, pos):
                continue

            if use.opcode == "mcopy" and pos == 1 and use is copy_inst:
                copy_seen = True
                continue

            if use.opcode == "invoke" and pos == 1:
                if use.parent is not copy_bb:
                    return False
                if bb_insts.index(use) >= copy_idx:
                    return False
                if not self._invoke_has_return_buffer(use):
                    return False
                invoke_sites.add(use)
                continue

            return False

        return copy_seen and len(invoke_sites) == 1

    def _invoke_may_clobber_src(self, invoke_inst: IRInstruction, src_loc: MemoryLocation) -> bool:
        for pos, op in enumerate(invoke_inst.operands):
            if pos == 0:
                continue
            if not self._invoke_operand_may_write(invoke_inst, pos):
                continue
            if not isinstance(op, IRVariable):
                continue

            ptr = self.base_ptr.ptr_from_op(op)
            if ptr is None:
                # Writable operand with unknown pointer shape.
                return True

            op_loc = MemoryLocation(offset=ptr.offset, size=None, alloca=ptr.base_alloca)
            if self.mem_alias.may_alias(src_loc, op_loc):
                return True

        return False

    def _invoke_operand_may_write(self, invoke_inst: IRInstruction, operand_pos: int) -> bool:
        if operand_pos == 1 and self._invoke_has_return_buffer(invoke_inst):
            return True
        return not self._is_readonly_invoke_operand(invoke_inst, operand_pos)
