from vyper.venom.analysis import IRAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand


class VarEquivalenceAnalysis(IRAnalysis):
    """
    Generate equivalence sets of variables. This is used to avoid swapping
    variables which are the same during venom_to_assembly. Theoretically,
    the DFTPass should order variable declarations optimally, but, it is
    not aware of the "pickaxe" heuristic in venom_to_assembly, so they can
    interfere.
    """

    def analyze(self):
        self._equivalence_set: dict[IROperand, int] = {}

        # dict from bags to literal values
        self._literals: dict[int, IRLiteral] = {}

        bag = 0
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "store":
                    continue
                self._handle_store(inst, bag)
                bag += 1

    def _handle_store(self, inst: IRInstruction, bag: int):
        var = inst.output
        source = inst.operands[0]

        assert var is not None  # help mypy
        assert var not in self._equivalence_set  # invariant

        if source in self._equivalence_set:
            bag = self._equivalence_set[source]
            self._equivalence_set[var] = bag
        else:
            self._equivalence_set[source] = bag
            self._equivalence_set[var] = bag

        if isinstance(source, IRLiteral):
            self._literals[bag] = source

    def equivalent(self, var1, var2):
        if var1 not in self._equivalence_set:
            return False
        if var2 not in self._equivalence_set:
            return False
        return self._equivalence_set[var1] == self._equivalence_set[var2]

    def get_literal(self, var):
        if (bag := self._equivalence_set.get(var)) is None:
            return None
        return self._literals.get(bag)
