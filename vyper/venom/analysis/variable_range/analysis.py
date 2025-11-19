from __future__ import annotations

from collections import deque
from typing import Iterable, Optional

from vyper.utils import wrap256
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, IRAnalysis
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)

from .evaluators import EVAL_DISPATCH
from .value_range import SIGNED_MAX, SIGNED_MIN, UNSIGNED_MAX, RangeState, ValueRange


class VariableRangeAnalysis(IRAnalysis):
    """
    Flow-sensitive range analysis over Venom IR.

    Keeps environments at block entries/exits plus a snapshot before every
    instruction so clients can query ranges at arbitrary points.
    """

    cfg: CFGAnalysis
    dfg: DFGAnalysis
    _entry_state: dict[IRBasicBlock, Optional[RangeState]]  # range state at block entry
    _exit_state: dict[IRBasicBlock, Optional[RangeState]]  # range state at block exit
    _inst_entry_env: dict[IRInstruction, RangeState]  # range state before each instruction
    _visit_count: dict[IRBasicBlock, int]  # number of times block visited (for widening)

    # after this many visits to a block, start applying widening
    WIDEN_THRESHOLD = 2

    def analyze(self) -> None:
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self._entry_state = {bb: None for bb in self.function.get_basic_blocks()}
        self._exit_state = {bb: None for bb in self.function.get_basic_blocks()}
        self._inst_entry_env = {}
        self._visit_count = {bb: 0 for bb in self.function.get_basic_blocks()}

        worklist = deque([self.function.entry])

        while worklist:
            bb = worklist.popleft()
            self._visit_count[bb] += 1

            entry_state = self._compute_entry_state(bb)
            if entry_state != self._entry_state[bb]:
                self._entry_state[bb] = entry_state
            exit_state = self._run_block(bb, entry_state)

            if exit_state != self._exit_state[bb]:
                self._exit_state[bb] = exit_state
                for succ in self.cfg.cfg_out(bb):
                    if succ not in worklist:
                        worklist.append(succ)

    def get_range(self, operand: IROperand, inst: IRInstruction) -> ValueRange:
        """
        Get the variable's value range of an operand at the point
        just before a given instruction.
        """
        if isinstance(operand, IRLiteral):
            return ValueRange.constant(operand.value)
        if not isinstance(operand, IRVariable):
            return ValueRange.top()

        env = self._inst_entry_env.get(inst)
        if env is None:
            return ValueRange.top()
        return env.get(operand, ValueRange.top())

    def _compute_entry_state(self, bb: IRBasicBlock) -> RangeState:
        """
        Compute incoming environment for a block, handling phis and widening.
        """
        if len(self.cfg.cfg_in(bb)) == 0:
            state: RangeState = {}
        else:
            pred_states: dict[IRBasicBlock, RangeState] = {}
            for pred in self.cfg.cfg_in(bb):
                pred_states[pred] = self._edge_state(pred, bb)
            state = self._join_states(pred_states.values())
            state = self._normalize_state(state)

            # Apply widening if visited too many times (loop back-edge)
            if self._visit_count[bb] > self.WIDEN_THRESHOLD:
                old_state = self._entry_state[bb]
                if old_state is not None:
                    state = self._widen_states(old_state, state)

        for inst in bb.instructions:
            if inst.opcode != "phi" or inst.output is None:
                break
            phi_range = self._phi_range(inst)
            self._write_range(state, inst.output, phi_range)

        return state

    def _run_block(self, bb: IRBasicBlock, entry_state: RangeState) -> RangeState:
        env = self._copy_state(entry_state)

        for inst in bb.instructions:
            self._inst_entry_env[inst] = self._copy_state(env)

            if inst.opcode == "phi" or not inst.has_outputs:
                continue

            new_range = self._evaluate_inst(inst, env)
            if new_range is not None:
                for output in inst.get_outputs():
                    self._write_range(env, output, new_range)

        return env

    def _evaluate_inst(self, inst: IRInstruction, env: RangeState) -> Optional[ValueRange]:
        """
        Return the resulting range for an instruction, if it can be computed
        """
        opcode = inst.opcode

        handler = EVAL_DISPATCH.get(opcode)
        if handler is None:
            return ValueRange.top() if inst.has_outputs else None
        return handler(inst, env)

    def _phi_range(self, inst: IRInstruction) -> ValueRange:
        assert inst.opcode == "phi"
        phi_range = ValueRange.empty()
        for label, var in inst.phi_operands:
            pred_bb = self.function.get_basic_block(label.value)
            pred_state = self._edge_state(pred_bb, inst.parent)
            assert isinstance(var, IRVariable)  # phi operands are always variables
            phi_range = phi_range.union(pred_state.get(var, ValueRange.top()))
        return phi_range if not phi_range.is_empty else ValueRange.top()

    def _edge_state(self, pred: IRBasicBlock, succ: IRBasicBlock) -> RangeState:
        pred_exit = self._exit_state[pred]
        # If predecessor hasn't been processed yet, use empty state
        if pred_exit is None:
            return {}

        state = self._copy_state(pred_exit)
        term = pred.instructions[-1]
        if term.opcode != "jnz":
            return state

        cond, true_label, false_label = term.operands
        branch: Optional[bool] = None
        if isinstance(true_label, IRLabel) and true_label.value == succ.label.value:
            branch = True
        elif isinstance(false_label, IRLabel) and false_label.value == succ.label.value:
            branch = False

        if branch is None:
            return state
        return self._apply_condition(cond, branch, state)

    def _apply_condition(self, operand: IROperand, is_true: bool, state: RangeState) -> RangeState:
        if isinstance(operand, IRLiteral):
            return state
        if not isinstance(operand, IRVariable):
            return state

        inst = self.dfg.get_producing_instruction(operand)
        if inst is None:
            return state

        if inst.opcode == "assign":
            inner_op = inst.operands[-1]
            return self._apply_condition(inner_op, is_true, state)

        if inst.opcode == "iszero":
            return self._apply_iszero(inst, is_true, state)
        if inst.opcode == "eq":
            return self._apply_eq(inst, is_true, state)
        if inst.opcode in {"lt", "gt", "slt", "sgt"}:
            return self._apply_compare(inst, is_true, state)

        return state

    def _apply_iszero(self, inst: IRInstruction, is_true: bool, state: RangeState) -> RangeState:
        target = inst.operands[-1]
        if not isinstance(target, IRVariable):
            return state
        if is_true:
            self._write_range(state, target, ValueRange.constant(0))
        else:
            current = state.get(target, ValueRange.top())
            # On false branch, value is non-zero. Intersect with [1, UNSIGNED_MAX]
            nonzero_range = ValueRange((1, UNSIGNED_MAX))
            new_range = current.intersect(nonzero_range)
            if not new_range.is_empty:
                self._write_range(state, target, new_range)
        return state

    def _apply_eq(self, inst: IRInstruction, is_true: bool, state: RangeState) -> RangeState:
        lhs, rhs = inst.operands[-1], inst.operands[-2]
        if not is_true:
            return state

        if isinstance(lhs, IRVariable) and isinstance(rhs, IRLiteral):
            self._write_range(state, lhs, ValueRange.constant(rhs.value))
        elif isinstance(rhs, IRVariable) and isinstance(lhs, IRLiteral):
            self._write_range(state, rhs, ValueRange.constant(lhs.value))
        elif isinstance(lhs, IRVariable) and isinstance(rhs, IRVariable):
            lhs_range = state.get(lhs, ValueRange.top())
            rhs_range = state.get(rhs, ValueRange.top())
            new_range = lhs_range.intersect(rhs_range)
            self._write_range(state, lhs, new_range)
            self._write_range(state, rhs, new_range)
        return state

    def _apply_compare(self, inst: IRInstruction, is_true: bool, state: RangeState) -> RangeState:
        lhs, rhs = inst.operands[-1], inst.operands[-2]
        signed = inst.opcode in {"slt", "sgt"}
        min_bound = SIGNED_MIN if signed else 0
        max_bound = SIGNED_MAX if signed else UNSIGNED_MAX

        if isinstance(lhs, IRVariable) and isinstance(rhs, IRLiteral):
            bound = wrap256(rhs.value, signed=signed)
            self._narrow_var(
                state, lhs, bound, inst.opcode, is_true, min_bound, max_bound, left_side=True
            )
        elif isinstance(lhs, IRLiteral) and isinstance(rhs, IRVariable):
            bound = wrap256(lhs.value, signed=signed)
            self._narrow_var(
                state, rhs, bound, inst.opcode, is_true, min_bound, max_bound, left_side=False
            )
        return state

    def _narrow_var(
        self,
        state: RangeState,
        var: IRVariable,
        bound: int,
        opcode: str,
        is_true: bool,
        min_bound: int,
        max_bound: int,
        *,
        left_side: bool,
    ) -> None:
        current = state.get(var, ValueRange.top())
        if opcode in {"lt", "slt"}:
            if left_side:
                if is_true:
                    self._write_range(state, var, current.clamp(min_bound, bound - 1))
                else:
                    self._write_range(state, var, current.clamp(bound, max_bound))
            else:
                if is_true:
                    self._write_range(state, var, current.clamp(bound + 1, max_bound))
                else:
                    self._write_range(state, var, current.clamp(min_bound, bound))
        elif opcode in {"gt", "sgt"}:
            if left_side:
                if is_true:
                    self._write_range(state, var, current.clamp(bound + 1, max_bound))
                else:
                    self._write_range(state, var, current.clamp(min_bound, bound))
            else:
                if is_true:
                    self._write_range(state, var, current.clamp(min_bound, bound - 1))
                else:
                    self._write_range(state, var, current.clamp(bound, max_bound))

    def _join_states(self, states: Iterable[RangeState]) -> RangeState:
        merged: RangeState = {}
        for state in states:
            for var, rng in state.items():
                if var in merged:
                    merged[var] = merged[var].union(rng)
                else:
                    merged[var] = rng
        return merged

    def _write_range(self, state: RangeState, var: IRVariable, rng: ValueRange) -> None:
        if rng.is_top:
            state.pop(var, None)
        else:
            state[var] = rng

    def _copy_state(self, state: RangeState) -> RangeState:
        return dict(state)

    def _normalize_state(self, state: RangeState) -> RangeState:
        to_delete = [var for var, rng in state.items() if rng.is_top]
        for var in to_delete:
            del state[var]
        return state

    def _widen_states(self, old_state: RangeState, new_state: RangeState) -> RangeState:
        """
        Widen per-variable ranges to guarantee convergence in loops
        """
        result = self._copy_state(new_state)
        for var in result:
            old_range = old_state.get(var, ValueRange.top())
            new_range = result[var]
            widened = self._widen_range(old_range, new_range)
            result[var] = widened
        return result

    def _widen_range(self, old_range: ValueRange, new_range: ValueRange) -> ValueRange:
        """
        Return a widened range between two iterations.

        If the new bounds exceed the previous ones, widen to TOP; otherwise keep
        the new (tighter or equal) bounds.
        """
        if old_range.is_top or new_range.is_top:
            return ValueRange.top()
        if old_range.is_empty:
            return new_range
        if new_range.is_empty:
            return old_range

        # If the range is growing, widen to top
        if new_range.lo < old_range.lo or new_range.hi > old_range.hi:
            return ValueRange.top()

        return new_range
