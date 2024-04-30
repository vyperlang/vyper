from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.passes.base_pass import IRPass


class RemoveUnusedVariablesPass(IRPass):
    def run_pass(self):
        removeList = set()

        self.manager.request_analysis(LivenessAnalysis)

        for bb in self.manager.function.basic_blocks:
            for i, inst in enumerate(bb.instructions[:-1]):
                if inst.volatile:
                    continue
                next_liveness = bb.instructions[i + 1].liveness
                if (inst.output and inst.output not in next_liveness) or inst.opcode == "nop":
                    removeList.add(inst)

            bb.instructions = [inst for inst in bb.instructions if inst not in removeList]

        self.manager.invalidate_analysis(DFGAnalysis)
