from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import vyper.venom.effects as effects
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.passes.base_pass import InstUpdater, IRPass


@dataclass
class _MergeCandidate:
    """
    Represents a pair of assert instructions that can be merged.
    """

    first: IRInstruction  # the assert to remove
    first_pred: IROperand  # operand of the iszero for first assert
    second: IRInstruction  # the assert to keep (and modify)
    second_pred: IROperand  # operand of the iszero for second assert


class _AssertCombineAnalysis:
    """
    Analysis phase: identifies pairs of `assert iszero(x)` instructions
    that can be combined into a single assert using `or`.
    """

    dfg: DFGAnalysis

    def __init__(self, dfg: DFGAnalysis):
        self.dfg = dfg

    def analyze(self, bb: IRBasicBlock) -> list[_MergeCandidate]:
        """
        Analyze a basic block and return a list of merge candidates.
        Each candidate represents a pair of asserts that can be merged.
        """
        candidates: list[_MergeCandidate] = []
        pending_assert: Optional[IRInstruction] = None
        pending_pred: Optional[IROperand] = None

        for inst in bb.instructions:
            if inst.opcode != "assert":
                if pending_assert is not None and not self._is_safe_between(inst):
                    pending_assert = pending_pred = None
                continue

            # inst.opcode == "assert"
            pred = self._get_iszero_operand(inst.operands[0])
            if pred is None:
                pending_assert = pending_pred = None
                continue

            if pending_assert is not None and self._can_merge(pending_assert, inst):
                assert pending_pred is not None  # invariant: set together with pending_assert
                candidates.append(
                    _MergeCandidate(
                        first=pending_assert, first_pred=pending_pred, second=inst, second_pred=pred
                    )
                )
                # Chain: the merged result becomes the new pending
                # We'll compute the actual merged predicate in the transform phase
                pending_assert, pending_pred = inst, self._compute_merged_pred(pending_pred, pred)
                continue

            # start new pending chain
            pending_assert, pending_pred = inst, pred

        return candidates

    def _compute_merged_pred(self, a_pred: IROperand, b_pred: IROperand) -> IROperand:
        """
        Compute what the merged predicate will be.
        For identical preds, it stays the same. Otherwise, it will be an `or`.
        We use b_pred as a placeholder since the actual or variable is created
        during transformation.
        """
        if a_pred == b_pred:
            return a_pred
        # Return b_pred as placeholder - the actual `or` result will be created
        # during transformation and the chain will be updated
        return b_pred

    def _can_merge(self, a: IRInstruction, b: IRInstruction) -> bool:
        if a.error_msg != b.error_msg:
            return False
        if len(a.operands) != 1 or len(b.operands) != 1:
            return False
        return True

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
        """
        Follow `op` through assigns to find an iszero instruction.
        Returns the iszero's operand (the value being zero-checked), or None
        if `op` doesn't resolve to an iszero pattern.

        Note: rejects literal inputs (can't trace through them) but the
        returned operand may be a literal (e.g., `iszero 0`).
        """
        # can only trace through variables, not literals
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


class AssertCombinerPass(IRPass):
    """
    Combine `assert iszero(x)` sequences into a single assert using `or`.

    This pass has two phases:
    1. Analysis: identify pairs of asserts that can be merged
    2. Transformation: apply the merges
    """

    dfg: DFGAnalysis
    updater: InstUpdater

    def run_pass(self) -> None:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        analysis = _AssertCombineAnalysis(self.dfg)

        for bb in self.function.get_basic_blocks():
            candidates = analysis.analyze(bb)
            self._apply_merges(candidates)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _apply_merges(self, candidates: list[_MergeCandidate]) -> None:
        """
        Apply the merge transformations identified by the analysis phase.
        """
        # Track the current predicate for chained merges
        # Maps second instruction -> actual merged predicate
        merged_preds: dict[IRInstruction, IROperand] = {}

        for candidate in candidates:
            # Get the actual predicate for the first assert (may have been merged)
            first_pred = merged_preds.get(candidate.first, candidate.first_pred)
            second_pred = candidate.second_pred

            merged_pred = self._merge_asserts(
                candidate.first, first_pred, candidate.second, second_pred
            )
            if merged_pred is not None:
                merged_preds[candidate.second] = merged_pred

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
