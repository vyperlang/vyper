from vyper.venom.analysis import DFGAnalysis, IRAnalysis
from vyper.venom.basicblock import IRVariable


class VarEquivalenceAnalysis(IRAnalysis):
    """
    Generate equivalence sets of variables. This is used to avoid swapping
    variables which are the same during venom_to_assembly. Theoretically,
    the DFTPass should order variable declarations optimally, but, it is
    not aware of the "pickaxe" heuristic in venom_to_assembly, so they can
    interfere.
    """

    def analyze(self):
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        equivalence_set: dict[IRVariable, int] = {}

        for bag, (var, inst) in enumerate(dfg._dfg_outputs.items()):
            if inst.opcode != "store":
                continue

            source = inst.operands[0]

            assert var not in equivalence_set  # invariant
            if source in equivalence_set:
                equivalence_set[var] = equivalence_set[source]
                continue
            else:
                equivalence_set[var] = bag
                equivalence_set[source] = bag

        self._equivalence_set = equivalence_set

    def equivalent(self, var1, var2):
        if var1 not in self._equivalence_set:
            return False
        if var2 not in self._equivalence_set:
            return False
        return self._equivalence_set[var1] == self._equivalence_set[var2]
