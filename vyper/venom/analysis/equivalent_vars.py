from vyper.venom.analysis import IRAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand


class VarEquivalenceAnalysis(IRAnalysis):
    """
    Generate equivalence sets of variables. This is used in passes so that
    they can "peer through" store chains
    """

    def analyze(self):
        # map from variables to "equivalence set" of variables, denoted
        # by "bag" (an int).
        self._bags: dict[IRVariable, int] = {}

        # dict from bags to literal values
        self._literals: dict[int, IRLiteral] = {}

        # the root of the store chain
        self._root_instructions: dict[int, IRInstruction] = {}

        bag = 0
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.output is None:
                    continue
                if inst.opcode != "store":
                    self._handle_nonstore(inst, bag)
                else:
                    self._handle_store(inst, bag)
                bag += 1

    def _handle_nonstore(self, inst: IRInstruction, bag: int):
        if bag in self._bags:
            bag = self._bags[inst.output]
        else:
            self._bags[inst.output] = bag
        self._root_instructions[bag] = inst

    def _handle_store(self, inst: IRInstruction, bag: int):
        var = inst.output
        source = inst.operands[0]

        assert var is not None  # help mypy
        assert var not in self._bags # invariant

        if source in self._bags:
            bag = self._bags[source]
            self._bags[var] = bag
        else:
            self._bags[source] = bag
            self._bags[var] = bag

        if isinstance(source, IRLiteral):
            self._literals[bag] = source

    def equivalent(self, var1: IROperand, var2: IROperand):
        if var1 == var2:
            return True
        if var1 not in self._bags:
            return False
        if var2 not in self._bags:
            return False
        return self._bags[var1] == self._bags[var2]

    def get_literal(self, var: IROperand) -> IRLiteral:
        if isinstance(var, IRLiteral):
            return var
        if (bag := self._bags.get(var)) is None:
            return None
        return self._literals.get(bag)

    def get_root_instruction(self, var: IROperand):
        if (bag := self._bags.get(var)) is None:
            return None
        return self._root_instruction.get(var)
