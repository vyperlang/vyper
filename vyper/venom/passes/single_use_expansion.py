from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IRVariable
from vyper.venom.passes.base_pass import IRPass


class SingleUseExpansion(IRPass):
    """
    This pass transforms venom IR to "single use" form. It extracts literals
    and variables so that they can be reordered by the DFT pass. It creates
    two invariants:
    - each variable is used at most once (by any opcode besides a simple
      assignment)
    - operands to all instructions (besides assignment instructions) must
      be variables.

    these two properties are helpful for DFT and venom_to_assembly.py, and
    in fact the first invariant is *required* by venom_to_assembly.py.

    This pass is in some sense the "inverse" of AssignElimination.
    """

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_bb(self, bb):
        i = 0
        while i < len(bb.instructions):
            inst = bb.instructions[i]
            if inst.opcode in ("assign", "offset", "phi", "param"):
                i += 1
                continue

            for j, op in enumerate(inst.operands):
                # first operand to log is magic
                if inst.opcode == "log" and j == 0:
                    continue

                if isinstance(op, IRVariable):
                    uses = self.dfg.get_uses(op)
                    # it's already only used once
                    if len(uses) == 1 and len([x for x in inst.operands if x == op]) == 1:
                        continue

                if not isinstance(op, (IRLiteral, IRVariable)):
                    # IRLabels are special in certain instructions (e.g., jmp)
                    # skip them for now.
                    continue

                var = self.function.get_next_variable()
                to_insert = IRInstruction("assign", [op], var)
                bb.insert_instruction(to_insert, index=i)
                inst.operands[j] = var
                i += 1

            i += 1
