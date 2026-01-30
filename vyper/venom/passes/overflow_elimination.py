"""
Overflow Check Elimination Pass

This pass eliminates redundant arithmetic overflow/underflow checks
when Value Range Analysis can prove they will always pass.

Patterns eliminated:

1. Unsigned add overflow: assert (iszero (lt (add x y), x))
   - Eliminated when x,y are non-negative and max(x) + max(y) <= 2**256 - 1
   - Proof: if x,y are unsigned and x + y does not wrap, then x + y >= x

2. Unsigned sub underflow: assert (iszero (gt (sub x y), x))
   - Eliminated when x,y are non-negative and min(x) >= max(y)
   - Proof: if x >= y, then x - y <= x, so (x - y) > x is always false
"""

from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.variable_range import VariableRangeAnalysis
from vyper.venom.analysis.variable_range.value_range import UNSIGNED_MAX, ValueRange
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.passes.base_pass import IRPass


class OverflowEliminationPass(IRPass):
    """
    Eliminates arithmetic overflow checks that VRA proves are always safe.
    """

    def run_pass(self) -> int:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.range_analysis = self.analyses_cache.force_analysis(VariableRangeAnalysis)

        # Collect all assert instructions
        asserts: list[IRInstruction] = []
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "assert":
                    asserts.append(inst)

        if not asserts:
            return 0

        changes = 0
        for inst in asserts:
            if self._try_eliminate_overflow_check(inst):
                inst.make_nop()
                changes += 1

        if changes > 0:
            self.analyses_cache.invalidate_analysis(VariableRangeAnalysis)
            self.analyses_cache.invalidate_analysis(DFGAnalysis)
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)

        return changes

    def _try_eliminate_overflow_check(self, assert_inst: IRInstruction) -> bool:
        """
        Try to eliminate an overflow check assertion.
        Returns True if the assertion can be safely removed.
        """
        # If an error message is set, only consider safeadd/safesub checks
        if assert_inst.error_msg is not None and assert_inst.error_msg not in {
            "safeadd",
            "safesub",
        }:
            return False

        operand = assert_inst.operands[0]

        # Pattern: assert %ok where %ok = iszero %cmp
        iszero_inst = self._get_producer(operand)
        if iszero_inst is None or iszero_inst.opcode != "iszero":
            return False

        cmp_operand = iszero_inst.operands[0]

        # Pattern: %ok = iszero %cmp where %cmp = lt/gt %res, %x
        cmp_inst = self._get_producer(cmp_operand)
        if cmp_inst is None:
            return False

        if cmp_inst.opcode == "lt":
            return self._try_eliminate_add_overflow(cmp_inst)
        elif cmp_inst.opcode == "gt":
            return self._try_eliminate_sub_underflow(cmp_inst)

        return False

    def _try_eliminate_add_overflow(self, lt_inst: IRInstruction) -> bool:
        """
        Eliminate: lt (add x y), x
        Condition: x,y non-negative and max(x)+max(y) fits in 256 bits

        Pattern in Venom IR (reversed operand order):
          lt %res, %x  means  %res < %x
          operands[-1] = %res (first in text)
          operands[-2] = %x (second in text)
        """
        # lt %res, %x -> operands are [%x, %res] in list, but semantically res < x
        res_operand = lt_inst.operands[-1]  # First in text = result being compared
        x_operand = lt_inst.operands[-2]  # Second in text = original operand

        # Check if res is produced by an add instruction
        add_inst = self._get_producer(res_operand)
        if add_inst is None or add_inst.opcode != "add":
            return False

        # add %x, %y -> find which operand is x and which is y
        add_op0 = add_inst.operands[0]
        add_op1 = add_inst.operands[1]

        # Determine which add operand matches x_operand
        if self._operands_match(add_op0, x_operand):
            y_operand = add_op1
        elif self._operands_match(add_op1, x_operand):
            y_operand = add_op0
        else:
            # x_operand doesn't match either add operand
            return False

        # Check operand ranges using VRA
        x_range = self.range_analysis.get_range(x_operand, add_inst)
        y_range = self.range_analysis.get_range(y_operand, add_inst)
        if not self._range_is_non_negative(x_range) or not self._range_is_non_negative(y_range):
            return False

        # If max(x) + max(y) fits in 256 bits, overflow is impossible
        return (x_range.hi + y_range.hi) <= UNSIGNED_MAX

    def _try_eliminate_sub_underflow(self, gt_inst: IRInstruction) -> bool:
        """
        Eliminate: gt (sub x y), x
        Condition: x,y non-negative and min(x) >= max(y)

        Pattern in Venom IR:
          gt %res, %x  means  %res > %x
          operands[-1] = %res (first in text)
          operands[-2] = %x (second in text)
        """
        res_operand = gt_inst.operands[-1]  # First in text = result being compared
        x_operand = gt_inst.operands[-2]  # Second in text = original operand

        # Check if res is produced by a sub instruction
        sub_inst = self._get_producer(res_operand)
        if sub_inst is None or sub_inst.opcode != "sub":
            return False

        # sub %x, %y -> operands[-1] = x, operands[-2] = y
        sub_x = sub_inst.operands[-1]  # First operand (minuend)
        sub_y = sub_inst.operands[-2]  # Second operand (subtrahend)

        # Check that the comparison x matches the sub's first operand
        if not self._operands_match(sub_x, x_operand):
            return False

        # Check operand ranges using VRA
        x_range = self.range_analysis.get_range(x_operand, sub_inst)
        y_range = self.range_analysis.get_range(sub_y, sub_inst)
        if not self._range_is_non_negative(x_range) or not self._range_is_non_negative(y_range):
            return False

        # If min(x) >= max(y), underflow is impossible
        return x_range.lo >= y_range.hi

    def _get_producer(self, operand) -> IRInstruction | None:
        """Get the instruction that produces this operand."""
        if not isinstance(operand, IRVariable):
            return None
        return self.dfg.get_producing_instruction(operand)

    def _operands_match(self, op1, op2) -> bool:
        """Check if two operands refer to the same value."""
        # Direct equality check
        if op1 == op2:
            return True

        # If both are variables, check if they're the same variable
        if isinstance(op1, IRVariable) and isinstance(op2, IRVariable):
            return op1 == op2

        return False

    def _range_is_non_negative(self, value_range: ValueRange) -> bool:
        """Return True if the range is known, non-empty, and non-negative."""
        return not value_range.is_top and not value_range.is_empty and value_range.lo >= 0
