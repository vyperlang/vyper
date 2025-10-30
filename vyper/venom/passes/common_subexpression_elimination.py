from vyper.venom.analysis.available_expression import (
    NONIDEMPOTENT_INSTRUCTIONS,
    AvailableExpressionAnalysis,
)
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction
from vyper.venom.passes.base_pass import IRPass

# instruction that dont need to be stored in available expression
UNINTERESTING_OPCODES = frozenset(
    [
        "calldatasize",
        "gaslimit",
        "address",
        "codesize",
        "assign",
        "phi",
        "param",
        "source",
        "nop",
        "returndatasize",
        "gas",
        "gasprice",
        "origin",
        "coinbase",
        "timestamp",
        "number",
        "prevrandao",
        "chainid",
        "basefee",
        "blobbasefee",
        "pc",
        "msize",
    ]
)
# instruction that are not useful to be # substituted
NO_SUBSTITUTE_OPCODES = UNINTERESTING_OPCODES | frozenset(["offset"])


SMALL_EXPRESSION = 1


class CSE(IRPass):
    expression_analysis: AvailableExpressionAnalysis

    def run_pass(self):
        self.expression_analysis = self.analyses_cache.request_analysis(AvailableExpressionAnalysis)

        while True:
            replace_dict = self._find_replaceble()
            if len(replace_dict) == 0:
                return

            self._replace(replace_dict)
            self.analyses_cache.invalidate_analysis(DFGAnalysis)
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)
            self.expression_analysis = self.analyses_cache.force_analysis(
                AvailableExpressionAnalysis
            )

    # return instruction and to which instruction it could
    # replaced by
    def _find_replaceble(self) -> dict[IRInstruction, IRInstruction]:
        res: dict[IRInstruction, IRInstruction] = dict()

        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                # skip instruction that for sure
                # wont be substituted
                if inst.opcode in NO_SUBSTITUTE_OPCODES:
                    continue
                if inst.opcode in NONIDEMPOTENT_INSTRUCTIONS:
                    continue
                state = self.expression_analysis.get_expression(inst)
                if state is None:
                    continue
                expr, replace_inst = state

                # heuristic to not replace small expressions across
                # basic block bounderies (it can create better codesize)
                if expr.depth > SMALL_EXPRESSION:
                    res[inst] = replace_inst
                else:
                    from_same_bb = self.expression_analysis.get_from_same_bb(inst, expr)
                    if len(from_same_bb) > 0:
                        # arbitrarily pick a replacement instruction
                        replace_inst = from_same_bb[0]
                        res[inst] = replace_inst

        return res

    def _replace(self, replace_dict: dict[IRInstruction, IRInstruction]):
        for orig, to in replace_dict.items():
            self._replace_inst(orig, to)

    def _replace_inst(self, orig_inst: IRInstruction, to_inst: IRInstruction):
        orig_outputs = orig_inst.get_outputs()
        if len(orig_outputs) > 0:
            orig_inst.opcode = "assign"
            to_outputs = to_inst.get_outputs()
            assert len(to_outputs) == 1, f"multiple outputs for {to_inst}"
            orig_inst.operands = [to_outputs[0]]
        else:
            orig_inst.opcode = "nop"
            orig_inst.operands = []
