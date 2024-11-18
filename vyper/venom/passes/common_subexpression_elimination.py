from vyper.utils import OrderedSet
from vyper.venom.analysis.available_expression import (
    _NONIDEMPOTENT_INSTRUCTIONS,
    UNINTERESTING_OPCODES,
    CSEAnalysis,
)
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.passes.base_pass import IRPass

_MAX_DEPTH = 5
_MIN_DEPTH = 2


class CSE(IRPass):
    expression_analysis: CSEAnalysis

    def run_pass(self, min_depth: int = _MIN_DEPTH, max_depth: int = _MAX_DEPTH):
        available_expression_analysis = self.analyses_cache.request_analysis(
            CSEAnalysis, min_depth, max_depth
        )
        assert isinstance(available_expression_analysis, CSEAnalysis)
        self.expression_analysis = available_expression_analysis

        while True:
            replace_dict = self._find_replaceble()
            if len(replace_dict) == 0:
                return
            self._replace(replace_dict)
            self.analyses_cache.invalidate_analysis(DFGAnalysis)
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)
            # should be ok to be reevaluted
            # self.available_expression_analysis.analyze(min_depth, max_depth)
            self.expression_analysis = self.analyses_cache.force_analysis(
                CSEAnalysis, min_depth, max_depth
            )  # type: ignore

    # return instruction and to which instruction it could
    # replaced by
    def _find_replaceble(self) -> dict[IRInstruction, IRInstruction]:
        res: dict[IRInstruction, IRInstruction] = dict()

        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                # skip instruction that for sure
                # wont be substituted
                if (
                    inst.opcode in UNINTERESTING_OPCODES
                    or inst.opcode in _NONIDEMPOTENT_INSTRUCTIONS
                ):
                    continue
                inst_expr = self.expression_analysis.get_expression(inst)
                avail = self.expression_analysis.get_available(inst)
                # heuristic to not replace small expressions
                # basic block bounderies (it can create better codesize)
                if inst_expr in avail and (
                    inst_expr.get_depth > 1 or inst.parent == inst_expr.inst.parent
                ):
                    res[inst] = inst_expr.inst

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
