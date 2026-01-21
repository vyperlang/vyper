from __future__ import annotations

from typing import Iterable, Optional

import vyper.venom.effects as effects
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class AssertCombinerPass(IRPass):
    """
    Combine `assert iszero(x)` sequences into a single assert using `or`.
    """

    dfg: DFGAnalysis
    updater: InstUpdater

    def run_pass(self) -> None:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        for bb in self.function.get_basic_blocks():
            self._combine_in_block(bb.instructions)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _combine_in_block(self, instructions: Iterable[IRInstruction]) -> None:
        pending_assert: Optional[IRInstruction] = None
        pending_pred: Optional[IROperand] = None

        for inst in list(instructions):
            if inst.opcode == "assert":
                pred = self._get_iszero_operand(inst.operands[0])
                if pred is None:
                    pending_assert = None
                    pending_pred = None
                    continue

                if pending_assert is not None:
                    if self._can_merge(pending_assert, inst):
                        merged_pred = self._merge_asserts(pending_assert, pending_pred, inst, pred)
                        if merged_pred is not None:
                            pending_assert = inst
                            pending_pred = merged_pred
                            continue

                pending_assert = inst
                pending_pred = pred
                continue

            if pending_assert is not None and not self._is_safe_between(inst):
                pending_assert = None
                pending_pred = None

    def _can_merge(self, a: IRInstruction, b: IRInstruction) -> bool:
        if a.error_msg != b.error_msg:
            return False
        if len(a.operands) != 1 or len(b.operands) != 1:
            return False
        return True

    def _merge_asserts(
        self, a: IRInstruction, a_pred: IROperand, b: IRInstruction, b_pred: IROperand
    ) -> Optional[IROperand]:
        if a_pred == b_pred:
            self.updater.remove(a)
            return a_pred

        or_var = self.updater.add_before(b, "or", [a_pred, b_pred])
        if or_var is None:
            return None

        iszero_var = self.updater.add_before(b, "iszero", [or_var])
        if iszero_var is None:
            return None

        self.updater.update(b, "assert", [iszero_var])
        self.updater.remove(a)
        return or_var

    def _is_safe_between(self, inst: IRInstruction) -> bool:
        if inst.is_bb_terminator:
            return False
        if inst.is_volatile:
            return False
        if inst.get_write_effects() != effects.EMPTY:
            return False
        if inst.get_read_effects() != effects.EMPTY:
            return False
        return True

    def _get_iszero_operand(
        self, op: IROperand, seen: Optional[set[IRVariable]] = None
    ) -> Optional[IROperand]:
        if isinstance(op, IRLiteral):
            return None
        if not isinstance(op, IRVariable):
            return None

        if seen is None:
            seen = set()
        if op in seen:
            return None
        seen.add(op)

        inst = self.dfg.get_producing_instruction(op)
        if inst is None:
            return None

        if inst.opcode == "assign":
            return self._get_iszero_operand(inst.operands[0], seen)

        if inst.opcode != "iszero":
            return None

        src = inst.operands[0]
        if isinstance(src, (IRLiteral, IRVariable)):
            return src
        return None
