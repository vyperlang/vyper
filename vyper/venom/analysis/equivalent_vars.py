from vyper.venom.analysis import DFGAnalysis, IRAnalysis


class VarEquivalenceAnalysis(IRAnalysis):
    """
    Generate equivalence sets of variables. Essentially, variables chained
    by store instructions are equivalent. These are used to avoid swapping
    variables which are the same during venom_to_assembly, and are produced
    by the StoreExpansionPass.
    """

    def analyze(self):
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self._equivalence_set = {}

        for output, inst in dfg.outputs.items():
            if inst.opcode != "store":
                continue

            self._equivalence_set[output] = self._get_equivalent(inst.operands[0])

    def _get_equivalent(self, var):
        while var in self._equivalence_set:
            var = self._equivalence_set[var]
        return var

    def equivalent(self, var1, var2):
        return self._get_equivalent(var1) == self._get_equivalent(var2)
