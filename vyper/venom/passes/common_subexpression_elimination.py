from vyper.utils import OrderedSet
from vyper.venom.analysis.available_expression import (
    _UNINTERESTING_OPCODES,
    AvailableExpressionAnalysis,
)
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.passes.base_pass import IRPass


class CSE(IRPass):
    available_expression_analysis: AvailableExpressionAnalysis

    def run_pass(self, *args, **kwargs):
        available_expression_analysis = self.analyses_cache.request_analysis(
            AvailableExpressionAnalysis
        )
        assert isinstance(available_expression_analysis, AvailableExpressionAnalysis)
        self.available_expression_analysis = available_expression_analysis

        while True:
            replace_dict = self._find_replaceble()
            if len(replace_dict) == 0:
                return
            self._replace(replace_dict)
            self.analyses_cache.invalidate_analysis(DFGAnalysis)
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    # return instruction and to which instruction it could
    # replaced by
    def _find_replaceble(self) -> dict[IRInstruction, IRInstruction]:
        res: dict[IRInstruction, IRInstruction] = dict()
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst in _UNINTERESTING_OPCODES:
                    continue
                inst_expr = self.available_expression_analysis.get_expression(inst)
                avail = self.available_expression_analysis.get_available(inst)
                if inst_expr in avail:
                    res[inst] = inst_expr.first_inst

        return res

    def _replace(self, replace_dict: dict[IRInstruction, IRInstruction]):
        for orig, to in replace_dict.items():
            while to in replace_dict.keys():
                to = replace_dict[to]
            self._replace_inst(orig, to)

    def _replace_inst(self, orig_inst: IRInstruction, to_inst: IRInstruction):
        visited: OrderedSet[IRBasicBlock] = OrderedSet()
        if orig_inst.output is not None:
            assert isinstance(orig_inst.output, IRVariable), f"not var {orig_inst}"
            assert isinstance(to_inst.output, IRVariable), f"not var {to_inst}"
            self._replace_inst_r(orig_inst.parent, orig_inst.output, to_inst.output, visited)
        orig_inst.parent.remove_instruction(orig_inst)

    def _replace_inst_r(
        self, bb: IRBasicBlock, orig: IRVariable, to: IRVariable, visited: OrderedSet[IRBasicBlock]
    ):
        if bb in visited:
            return
        visited.add(bb)

        for inst in bb.instructions:
            for i in range(len(inst.operands)):
                op = inst.operands[i]
                if op == orig:
                    inst.operands[i] = to

        for out in bb.cfg_out:
            self._replace_inst_r(out, orig, to, visited)
