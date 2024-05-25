from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.basicblock import IRInstruction, IROperand
from vyper.venom.passes.base_pass import IRPass


class AlgebraicOptimizationPass(IRPass):
    """
    This pass reduces algebraic evaluatable expressions.

    It currently optimizes:
        * iszero chains
    """

    def _optimize_iszero_chains(self) -> None:
        fn = self.function
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "iszero":
                    continue

                iszero_chain = self._get_iszero_chain(inst.operands[0])
                if len(iszero_chain) == 0:
                    continue

                if len(iszero_chain) % 2 == 1:
                    out_var = iszero_chain[-1].operands[0]
                else:
                    assert iszero_chain[-1].output is not None  # help mypy
                    out_var = iszero_chain[-1].output

                for use_inst in self.dfg.get_uses(inst.output):
                    if use_inst.opcode == "iszero":
                        continue
                    elif use_inst.opcode != "jnz" and len(iszero_chain) <= 1:
                        continue
                    use_inst.replace_operands({inst.output: out_var})

    def _get_iszero_chain(self, op: IROperand) -> list[IRInstruction]:
        chain = []

        while True:
            inst = self.dfg.get_producing_instruction(op)
            if inst is None or inst.opcode != "iszero":
                break
            op = inst.operands[0]
            chain.append(inst)

        return chain

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self._optimize_iszero_chains()

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(CFGAnalysis)
