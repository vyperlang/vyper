from vyper.venom.analysis import BasePtrAnalysis, MemLivenessAnalysis
from vyper.venom.basicblock import IRLiteral
from vyper.venom.passes.base_pass import IRPass


class DallocaPromotion(IRPass):
    """
    Promote dalloca to alloca when the size operand has been
    folded to a compile-time literal (e.g. by SCCP).
    """

    required_successors = ("ConcretizeMemLocPass",)

    def run_pass(self):
        promoted = False
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "dalloca":
                    continue
                if isinstance(inst.operands[0], IRLiteral):
                    inst.opcode = "alloca"
                    promoted = True

        if promoted:
            self.analyses_cache.invalidate_analysis(MemLivenessAnalysis)
            self.analyses_cache.invalidate_analysis(BasePtrAnalysis)
