from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.variable_range import ValueRange, VariableRangeAnalysis
from vyper.venom.basicblock import IRInstruction
from vyper.venom.passes.base_pass import IRPass


class AssertEliminationPass(IRPass):
    def run_pass(self):
        asserts: list[IRInstruction] = []
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "assert":
                    asserts.append(inst)

        if not asserts:
            return 0

        variable_ranges = self.analyses_cache.force_analysis(VariableRangeAnalysis)

        changes = 0
        for inst in asserts:
            operand = inst.operands[0]
            rng = variable_ranges.get_range(operand, inst)
            if self._range_excludes_zero(rng):
                inst.make_nop()
                changes += 1

        if changes > 0:
            self.analyses_cache.invalidate_analysis(VariableRangeAnalysis)
            self.analyses_cache.invalidate_analysis(DFGAnalysis)
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        return changes

    @staticmethod
    def _range_excludes_zero(rng: ValueRange) -> bool:
        if rng.is_empty:
            return False
        return rng.lo > 0 or rng.hi < 0
