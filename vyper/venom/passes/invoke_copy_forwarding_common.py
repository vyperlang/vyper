from __future__ import annotations

from collections import deque
from collections.abc import Iterator

import vyper.evm.address_space as addr_space
from vyper.venom.analysis import (
    BasePtrAnalysis,
    DFGAnalysis,
    DominatorTreeAnalysis,
    LivenessAnalysis,
    MemoryAliasAnalysis,
)
from vyper.venom.basicblock import IRInstruction, IRLabel, IRLiteral, IROperand, IRVariable
from vyper.venom.effects import EMPTY, Effects
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.machinery.inst_updater import InstUpdater


class InvokeCopyForwardingBase(IRPass):
    """
    Shared analyses and helpers for invoke-related memory copy forwarding passes.
    """

    dfg: DFGAnalysis
    domtree: DominatorTreeAnalysis
    base_ptr: BasePtrAnalysis
    mem_alias: MemoryAliasAnalysis
    updater: InstUpdater

    def _prepare(self) -> None:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.domtree = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.base_ptr = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.mem_alias = self.analyses_cache.request_analysis(MemoryAliasAnalysis)
        self.updater = InstUpdater(self.dfg)

    def _finish(self, changed: bool) -> None:
        if changed:
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _is_after(self, copy_inst: IRInstruction, use_inst: IRInstruction) -> bool:
        copy_bb = copy_inst.parent
        use_bb = use_inst.parent

        if use_bb is copy_bb:
            bb_insts = copy_bb.instructions
            return bb_insts.index(use_inst) > bb_insts.index(copy_inst)

        return self.domtree.dominates(copy_bb, use_bb)

    def _invoke_has_return_buffer(self, invoke_inst: IRInstruction) -> bool:
        callee = self._get_invoke_callee(invoke_inst)
        if callee is None:
            return False

        if callee._invoke_param_count is None or callee._has_memory_return_buffer_param is None:
            return False

        invoke_arg_count = len(invoke_inst.operands) - 1
        if invoke_arg_count != callee._invoke_param_count:
            return False

        return callee._has_memory_return_buffer_param

    def _is_alloca_like(self, inst: IRInstruction | None) -> bool:
        return inst is not None and inst.opcode in ("alloca", "calloca")

    def _matches_alloca_size(self, inst: IRInstruction, expected_size: int) -> bool:
        size = inst.operands[0]
        return isinstance(size, IRLiteral) and size.value == expected_size

    def _is_readonly_invoke_operand(self, invoke_inst: IRInstruction, operand_idx: int) -> bool:
        if operand_idx == 0:
            return False

        callee = self._get_invoke_callee(invoke_inst)
        if callee is None:
            return False

        readonly_idxs = callee._readonly_memory_invoke_arg_idxs
        return (operand_idx - 1) in readonly_idxs

    def _get_invoke_callee(self, invoke_inst: IRInstruction):
        target = invoke_inst.operands[0]
        if not isinstance(target, IRLabel):
            return None
        return self.function.ctx.functions.get(target)

    def _has_src_clobber_between(
        self, copy_inst: IRInstruction, rewrite_sites: set[tuple[IRInstruction, int]]
    ) -> bool:
        src_loc = self.base_ptr.get_read_location(copy_inst, addr_space.MEMORY)
        if src_loc.is_empty():
            return False

        bb_insts = copy_inst.parent.instructions
        copy_idx = bb_insts.index(copy_inst)

        for invoke_inst, _ in rewrite_sites:
            invoke_idx = bb_insts.index(invoke_inst)
            for inst in bb_insts[copy_idx + 1 : invoke_idx]:
                if inst.get_write_effects() & Effects.MEMORY == EMPTY:
                    continue
                write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)
                if self.mem_alias.may_alias(src_loc, write_loc):
                    return True

        return False

    def _collect_assign_aliases(self, root: IRVariable) -> set[IRVariable]:
        aliases: set[IRVariable] = {root}
        worklist = deque([root])

        while len(worklist) > 0:
            var = worklist.popleft()
            for use in self.dfg.get_uses(var):
                if use.opcode != "assign":
                    continue
                out = use.output
                if out in aliases:
                    continue
                aliases.add(out)
                worklist.append(out)

        return aliases

    def _iter_use_positions(self, var: IRVariable) -> Iterator[tuple[IRInstruction, int]]:
        for use in self.dfg.get_uses(var):
            for pos, op in enumerate(use.operands):
                if op == var:
                    yield use, pos

    def _iter_alias_use_positions(
        self, aliases: set[IRVariable]
    ) -> Iterator[tuple[IRVariable, IRInstruction, int]]:
        for var in aliases:
            for use, pos in self._iter_use_positions(var):
                yield var, use, pos

    def _is_assign_output_use(self, use: IRInstruction, operand_pos: int) -> bool:
        return use.opcode == "assign" and operand_pos == 0

    def _assign_root(self, op: IROperand) -> IROperand:
        if not isinstance(op, IRVariable):
            return op
        return self._assign_root_var(op)

    def _assign_root_var(self, var: IRVariable) -> IRVariable:
        while True:
            inst = self.dfg.get_producing_instruction(var)
            if inst is None or inst.opcode != "assign":
                return var
            parent = inst.operands[0]
            if not isinstance(parent, IRVariable):
                return var
            var = parent
