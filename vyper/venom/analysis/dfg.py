from typing import Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysesCache, IRAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IROperand, IRVariable
from vyper.venom.function import IRFunction


class DFGAnalysis(IRAnalysis):
    _dfg_inputs: dict[IRVariable, OrderedSet[IRInstruction]]
    _dfg_outputs: dict[IRVariable, IRInstruction]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self._dfg_inputs = dict()
        self._dfg_outputs = dict()

    # return uses of a given variable
    def get_uses(self, op: IRVariable) -> OrderedSet[IRInstruction]:
        return self._dfg_inputs.get(op, OrderedSet())

    def get_uses_in_bb(self, op: IRVariable, bb: IRBasicBlock):
        """
        Get uses of a given variable in a specific basic block.
        """
        return [inst for inst in self.get_uses(op) if inst.parent == bb]

    # the instruction which produces this variable.
    def get_producing_instruction(self, op: IRVariable) -> Optional[IRInstruction]:
        return self._dfg_outputs.get(op)

    def set_producing_instruction(self, op: IRVariable, inst: IRInstruction):
        self._dfg_outputs[op] = inst

    def add_use(self, op: IRVariable, inst: IRInstruction):
        uses = self._dfg_inputs.setdefault(op, OrderedSet())
        uses.add(inst)

    def remove_use(self, op: IRVariable, inst: IRInstruction):
        uses: OrderedSet = self._dfg_inputs.get(op, OrderedSet())
        uses.remove(inst)

    def are_equivalent(self, var1: IROperand, var2: IROperand) -> bool:
        if var1 == var2:
            return True

        if isinstance(var1, IRVariable) and isinstance(var2, IRVariable):
            var1 = self._traverse_store_chain(var1)
            var2 = self._traverse_store_chain(var2)

        return var1 == var2

    def _traverse_store_chain(self, var: IRVariable) -> IRVariable:
        while True:
            inst = self.get_producing_instruction(var)
            if inst is None or inst.opcode != "store":
                return var
            var = inst.operands[0]  # type: ignore

    @property
    def outputs(self) -> dict[IRVariable, IRInstruction]:
        return self._dfg_outputs

    def analyze(self):
        # Build DFG

        # %15 = add %13 %14
        # %16 = iszero %15
        # dfg_outputs of %15 is (%15 = add %13 %14)
        # dfg_inputs of %15 is all the instructions which *use* %15, ex. [(%16 = iszero %15), ...]
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                operands = inst.get_input_variables()
                res = inst.get_outputs()

                for op in operands:
                    inputs = self._dfg_inputs.setdefault(op, OrderedSet())
                    inputs.add(inst)

                for op in res:  # type: ignore
                    assert isinstance(op, IRVariable)
                    self._dfg_outputs[op] = inst

    def as_graph(self) -> str:
        """
        Generate a graphviz representation of the dfg
        """
        lines = ["digraph dfg_graph {"]
        for var, inputs in self._dfg_inputs.items():
            for input in inputs:
                for op in input.get_outputs():
                    if isinstance(op, IRVariable):
                        lines.append(f'    " {var.name} " -> " {op.name} "')

        lines.append("}")
        return "\n".join(lines)

    def invalidate(self):
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def __repr__(self) -> str:
        return self.as_graph()


class InstUpdater:
    """
    A helper class for updating instructions which also updates the
    basic block and dfg in place
    """

    def __init__(self, dfg: DFGAnalysis):
        self.dfg = dfg

    def update_operands(self, inst: IRInstruction, replace_dict: dict[IROperand, IROperand]):
        old_operands = inst.operands
        new_operands = [replace_dict[op] if op in replace_dict else op for op in old_operands]
        self.update(inst, inst.opcode, new_operands)

    def update(self, inst: IRInstruction, opcode: str, new_operands: list[IROperand]):
        assert opcode != "phi"
        # sanity
        assert all(isinstance(op, IROperand) for op in new_operands)

        old_operands = inst.operands

        for op in old_operands:
            if not isinstance(op, IRVariable):
                continue
            uses = self.dfg.get_uses(op)
            if inst in uses:
                uses.remove(inst)

        for op in new_operands:
            if isinstance(op, IRVariable):
                self.dfg.add_use(op, inst)

        inst.opcode = opcode
        inst.operands = new_operands

    def nop(self, inst: IRInstruction):
        inst.annotation = str(inst)  # copy IRInstruction.make_nop()
        self.update(inst, "nop", [])

    def store(self, inst: IRInstruction, op: IROperand):
        self.update(inst, "store", [op])

    def add_before(self, inst: IRInstruction, opcode: str, args: list[IROperand]) -> IRVariable:
        """
        Insert another instruction before the given instruction
        """
        assert opcode != "phi"
        index = inst.parent.instructions.index(inst)
        var = inst.parent.parent.get_next_variable()
        operands = list(args)
        new_inst = IRInstruction(opcode, operands, output=var)
        inst.parent.insert_instruction(new_inst, index)
        for op in new_inst.operands:
            if isinstance(op, IRVariable):
                self.dfg.add_use(op, new_inst)
        self.dfg.add_use(var, inst)
        self.dfg.set_producing_instruction(var, new_inst)
        return var
