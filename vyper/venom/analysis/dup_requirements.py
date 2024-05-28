from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysis


class DupRequirementsAnalysis(IRAnalysis):
    def analyze(self):
        for bb in self.function.get_basic_blocks():
            last_liveness = bb.out_vars
            for inst in reversed(bb.instructions):
                inst.dup_requirements = OrderedSet()
                ops = inst.get_input_variables()
                for op in ops:
                    if op in last_liveness:
                        inst.dup_requirements.add(op)
                last_liveness = inst.liveness
