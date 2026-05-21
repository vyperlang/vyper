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
        self._expand_phi_operands()
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _expand_phi_operands(self):
        for target in self.function.get_basic_blocks():
            phis = list(target.phi_instructions)
            if len(phis) == 0:
                continue

            operands_by_source: dict[IRVariable, list[tuple[IRInstruction, int]]]
            sources: dict[str, dict[IRVariable, list[tuple[IRInstruction, int]]]] = {}
            for phi in phis:
                for i in range(0, len(phi.operands), 2):
                    label, var = phi.operands[i], phi.operands[i + 1]
                    source = label.name
                    operands_by_source = sources.setdefault(source, {})
                    operands_by_source.setdefault(var, []).append((phi, i + 1))

            for source, operands in sources.items():
                source_bb = self.function.get_basic_block(source)
                insert_idx = len(source_bb.instructions) - 1

                for var, uses in operands.items():
                    for phi, operand_idx in uses[1:]:
                        new_var = self.function.get_next_variable()
                        to_insert = IRInstruction("assign", [var], outputs=[new_var])
                        source_bb.insert_instruction(to_insert, index=insert_idx)
                        insert_idx += 1
                        phi.operands[operand_idx] = new_var

    def _process_bb(self, bb):
        i = 0
        while i < len(bb.instructions):
            inst = bb.instructions[i]
            if inst.opcode in ("assign", "offset", "phi", "param"):
                i += 1
                continue

            ops = inst.operands.copy()

            for j, op in enumerate(ops):
                # first operand to log is magic
                if inst.opcode == "log" and j == 0:
                    continue

                if isinstance(op, IRVariable):
                    uses = self.dfg.get_uses(op)
                    if len(uses) == 1 and len([x for x in inst.operands if x == op]) == 1:
                        continue

                if not isinstance(op, (IRLiteral, IRVariable)):
                    # IRLabels are special in certain instructions (e.g., jmp)
                    # skip them for now.
                    continue

                var = self.function.get_next_variable()
                to_insert = IRInstruction("assign", [op], outputs=[var])
                bb.insert_instruction(to_insert, index=i)
                if len(inst.operands) > j:
                    inst.operands[j] = var
                i += 1

            i += 1
