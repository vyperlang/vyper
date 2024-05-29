from typing import Optional

from vyper.venom.analysis.analysis import IRAnalysesCache, IRAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.function import IRFunction


class DFGAnalysis(IRAnalysis):
    _dfg_inputs: dict[IRVariable, list[IRInstruction]]
    _dfg_outputs: dict[IRVariable, IRInstruction]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self._dfg_inputs = dict()
        self._dfg_outputs = dict()

    # return uses of a given variable
    def get_uses(self, op: IRVariable) -> list[IRInstruction]:
        return self._dfg_inputs.get(op, [])

    # the instruction which produces this variable.
    def get_producing_instruction(self, op: IRVariable) -> Optional[IRInstruction]:
        return self._dfg_outputs.get(op)

    def add_use(self, op: IRVariable, inst: IRInstruction):
        uses = self._dfg_inputs.setdefault(op, [])
        uses.append(inst)

    def remove_use(self, op: IRVariable, inst: IRInstruction):
        uses = self._dfg_inputs.get(op, [])
        uses.remove(inst)

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
                    inputs = self._dfg_inputs.setdefault(op, [])
                    inputs.append(inst)

                for op in res:  # type: ignore
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
