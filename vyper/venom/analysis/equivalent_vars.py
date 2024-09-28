from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.basicblock import IRVariable


class VarEquivalenceAnalysis(IRAnalysis):
    """
    Generate equivalence sets of variables
    """

    def analyze(self):
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        equivalence_set: dict[IRVariable, int] = {}

        for bag, (var, inst) in enumerate(dfg._dfg_outputs.items()):
            if inst.opcode != "store":
                continue

            source = inst.operands[0]

            if source in equivalence_set:
                equivalence_set[var] = equivalence_set[source]
                continue
            else:
                assert var not in equivalence_set
                equivalence_set[var] = bag
                equivalence_set[source] = bag

        self._equivalence_set = equivalence_set

    def equivalent(self, var1, var2):
        if var1 not in self._equivalence_set:
            return False
        if var2 not in self._equivalence_set:
            return False
        return self._equivalence_set[var1] == self._equivalence_set[var2]
