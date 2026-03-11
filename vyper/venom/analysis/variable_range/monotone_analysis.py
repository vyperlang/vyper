from vyper.venom.analysis.monotone_base import MonotoneAnalysis, LatticeBase, Direction
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis import DFGAnalysis
from vyper.venom.basicblock import IRInstruction, IRBasicBlock, IRVariable, IROperand, IRLiteral, IRLabel
from vyper.venom.function import IRFunction
from vyper.utils import wrap256

from .value_range import SIGNED_MAX, SIGNED_MIN, UNSIGNED_MAX, RangeState, ValueRange
from .evaluators import EVAL_DISPATCH
from dataclasses import dataclass
from collections import defaultdict
from typing import Optional

@dataclass
class RangeLattice(LatticeBase):
    data: RangeState

    def copy(self):
        return RangeLattice(self.data.copy())

class VariableRangeMonotoneAnalysis(MonotoneAnalysis[RangeLattice]):
    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)

        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.visited_counts: dict[tuple[IRBasicBlock, IRBasicBlock], int] = defaultdict(lambda : 0)

    def _direction(self) -> Direction:
        return Direction.Forward

    def _join(self, a: RangeLattice, b: RangeLattice) -> RangeLattice:
        common_vars = set(a.data.keys())
        common_vars.intersection_update(b.data.keys())

        merged: RangeState = {}
        for var in common_vars:
            rng = ValueRange.empty()
            rng = rng.union(a.data[var])
            rng = rng.union(b.data[var])
            if not rng.is_top:
                merged[var] = rng
        return RangeLattice(merged)

    def _bottom(self) -> RangeLattice:
        return RangeLattice(dict())

    def _transfer_function(self, inst: IRInstruction, input_lattice: RangeLattice) -> RangeLattice:
        if inst.opcode == "phi" or not inst.has_outputs:
            return input_lattice

        new_range = self._evaluate_inst(inst, input_lattice.data)
        for output in inst.get_outputs():
            self._write_range(input_lattice.data, output, new_range)

        return input_lattice

    def _write_range(self, state: RangeState, var: IRVariable, rng: ValueRange) -> None:
        if rng.is_top:
            state.pop(var, None)
        else:
            state[var] = rng

    def _evaluate_inst(self, inst: IRInstruction, env: RangeState) -> ValueRange:
        """
        Return the resulting range for an instruction.
        Unknown opcodes conservatively return TOP.
        """
        opcode = inst.opcode

        handler = EVAL_DISPATCH.get(opcode)
        if handler is None:
            return ValueRange.top()
        return handler(inst, env)

    def _edge_transfer(self, source: IRBasicBlock, target: IRBasicBlock, input_lattice: RangeLattice) -> RangeLattice:
        state = input_lattice.copy()
        term = source.instructions[-1]
        if term.opcode != "jnz":
            return state

        cond, true_label, false_label = term.operands
        branch: Optional[bool] = None
        if isinstance(true_label, IRLabel) and true_label.value == target.label.value:
            branch = True
        elif isinstance(false_label, IRLabel) and false_label.value == target.label.value:
            branch = False

        if branch is None:
            return state
        new_state = self._apply_condition(cond, branch, state.data)
        return RangeLattice(new_state)

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
        """Apply iszero-based branch refinement.

        On the true branch: value == 0
        On the false branch: value != 0

        IMPORTANT: For the false branch, we cannot simply intersect with
        [1, UNSIGNED_MAX] because that would exclude negative values.
        Negative values like -128 are non-zero (they're 0xFF...FF80 in unsigned).

        For ranges that include both negative and non-negative values,
        "non-zero" means we can only exclude exactly 0 from the range.
        If the range is [lo, hi] where lo <= 0 <= hi, we can narrow to
        [lo, -1] U [1, hi], but since we can only represent contiguous ranges,
        we have to be conservative.
        """
        target = inst.operands[-1]
        if not isinstance(target, IRVariable):
            return state
        if is_true:
            self._write_range(state, target, ValueRange.constant(0))
        else:
            current = state.get(target, ValueRange.top())
            # On false branch, value is non-zero.

            if current.is_top:
                # Can't narrow TOP meaningfully for non-zero
                return state
            if current.is_empty:
                return state

            if current.lo < 0:
                # Range includes negative values (which are all non-zero)
                if current.hi < 0:
                    # Range doesn't contain zero, no narrowing needed
                    return state
                elif current.hi == 0:
                    # Range is [lo, 0], narrow to [lo, -1]
                    new_range = current.clamp(None, -1)
                    if not new_range.is_empty:
                        self._write_range(state, target, new_range)
                # Range spans zero: [lo, hi] where lo < 0 < hi
                # Non-zero means [lo, -1] ∪ [1, hi], which we can't represent
                # Be conservative: don't narrow
            else:
                # Range is entirely non-negative, intersect with [1, UNSIGNED_MAX]
                # Write even if empty (BOTTOM) - means false branch is unreachable
                nonzero_range = ValueRange((1, UNSIGNED_MAX))
                new_range = current.intersect(nonzero_range)
                self._write_range(state, target, new_range)
        return state

    def _apply_eq(self, inst: IRInstruction, is_true: bool, state: RangeState) -> RangeState:
        lhs, rhs = inst.operands[-1], inst.operands[-2]
        if not is_true:
            return state

        if isinstance(lhs, IRVariable) and isinstance(rhs, IRLiteral):
            # Normalize literal to signed representation for range system
            self._write_range(state, lhs, ValueRange.constant(wrap256(rhs.value, signed=True)))
        elif isinstance(rhs, IRVariable) and isinstance(lhs, IRLiteral):
            # Normalize literal to signed representation for range system
            self._write_range(state, rhs, ValueRange.constant(wrap256(lhs.value, signed=True)))
        elif isinstance(lhs, IRVariable) and isinstance(rhs, IRVariable):
            lhs_range = state.get(lhs, ValueRange.top())
            rhs_range = state.get(rhs, ValueRange.top())
            new_range = lhs_range.intersect(rhs_range)
            self._write_range(state, lhs, new_range)
            self._write_range(state, rhs, new_range)
        return state

    def _apply_compare(self, inst: IRInstruction, is_true: bool, state: RangeState) -> RangeState:
        """Apply comparison-based branch refinement.

        IMPORTANT: For unsigned comparisons (lt, gt), if the variable's range
        spans the signed/unsigned boundary, we need to be careful:

        - `lt %x, bound` TRUE: x < bound in unsigned. Negative values are huge
          in unsigned (>= 2^255), so they can never be < bound for reasonable
          bounds. We CAN narrow to [0, bound-1].

        - `lt %x, bound` FALSE: x >= bound in unsigned. This includes BOTH
          values >= bound AND negative values (which are huge unsigned).
          We CANNOT narrow because we'd lose the negative range.

        - `gt %x, bound` TRUE: x > bound in unsigned. Negative values are huge
          so they satisfy this. We CANNOT narrow.

        - `gt %x, bound` FALSE: x <= bound in unsigned. Negative values don't
          satisfy this. We CAN narrow to [0, bound].

        In summary: for unsigned comparisons with ranges that could include
        negatives, we can only narrow in cases where the narrowed range
        would be purely non-negative.
        """
        lhs, rhs = inst.operands[-1], inst.operands[-2]
        signed = inst.opcode in {"slt", "sgt"}
        min_bound = SIGNED_MIN if signed else 0
        max_bound = SIGNED_MAX if signed else UNSIGNED_MAX

        if isinstance(lhs, IRVariable) and isinstance(rhs, IRLiteral):
            current = state.get(lhs, ValueRange.top())
            bound = wrap256(rhs.value, signed=signed)
            # For unsigned comparisons with ranges that could include negatives
            if not signed and (current.is_top or current.lo < 0):
                # Check if this is a "safe" narrowing case
                # lt true (var < bound): narrow to [0, bound-1] - safe, excludes negatives
                # lt false (var >= bound): would keep negatives - unsafe
                # gt true (var > bound): would keep negatives - unsafe
                # gt false (var <= bound): narrow to [0, bound] - safe, excludes negatives
                is_lt = inst.opcode == "lt"
                safe_to_narrow = (is_lt and is_true) or (not is_lt and not is_true)
                if not safe_to_narrow or bound > SIGNED_MAX:
                    return state
                # For safe narrowing, use 0 as min_bound to exclude negatives
                min_bound = 0
            self._narrow_var(
                state, lhs, bound, inst.opcode, is_true, min_bound, max_bound, left_side=True
            )
        elif isinstance(lhs, IRLiteral) and isinstance(rhs, IRVariable):
            current = state.get(rhs, ValueRange.top())
            bound = wrap256(lhs.value, signed=signed)
            # Same logic but with left_side=False (bound on left of comparison)
            # lt: bound < var, so var > bound => gt semantics for var
            # gt: bound > var, so var < bound => lt semantics for var
            if not signed and (current.is_top or current.lo < 0):
                is_lt = inst.opcode == "lt"
                # With bound on left: lt means var > bound, gt means var < bound
                # Safe: gt true (var < bound), lt false (var <= bound)
                safe_to_narrow = (not is_lt and is_true) or (is_lt and not is_true)
                if not safe_to_narrow or bound > SIGNED_MAX:
                    return state
                min_bound = 0
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
        """Narrow variable range based on comparison result.

        Note on boundary arithmetic: When bound == min_bound, `bound - 1` produces
        a value below min_bound. When bound == max_bound, `bound + 1` produces a
        value above max_bound. In both cases, clamp() correctly produces BOTTOM
        (empty range) since the resulting interval has lo > hi. This handles
        impossible conditions like `x < 0` (unsigned) or `x slt SIGNED_MIN`.
        """
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


    def get_range(self, operand: IROperand, inst: IRInstruction) -> ValueRange:
        """
        Get the variable's value range of an operand at the point
        just before a given instruction.

        Literals are normalized to signed representation since the range system
        uses signed bounds internally. This ensures values >= 2^255 are treated
        as negative numbers (e.g., 2^255 becomes SIGNED_MIN).
        """
        if isinstance(operand, IRLiteral):
            return ValueRange.constant(wrap256(operand.value, signed=True))
        if not isinstance(operand, IRVariable):
            return ValueRange.top()

        env = self.inst_lattice.get(inst)
        if env is None:
            return ValueRange.top()
        return env.data.get(operand, ValueRange.top())

