from vyper.utils import OrderedSet
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dominators import DominatorTreeAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IROperand, IRVariable
from vyper.venom.passes.base_pass import IRPass


class MakeSSA(IRPass):
    """
    This pass converts the function into Static Single Assignment (SSA) form.
    """

    dom: DominatorTreeAnalysis
    defs: dict[IRVariable, OrderedSet[IRBasicBlock]]

    def run_pass(self):
        fn = self.function

        self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)

        # Request liveness analysis so the `liveness_in_vars` field is valid
        self.analyses_cache.request_analysis(LivenessAnalysis)

        self._add_phi_nodes()

        self.var_name_counters = {var.name: 0 for var in self.defs.keys()}
        self.var_name_stacks = {var.name: [0] for var in self.defs.keys()}
        self._rename_vars(fn.entry)
        self._remove_degenerate_phis(fn.entry)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _add_phi_nodes(self):
        """
        Add phi nodes to the function.
        """
        self._compute_defs()
        work = {var: 0 for var in self.dom.dfs_walk}
        has_already = {var: 0 for var in self.dom.dfs_walk}
        i = 0

        # Iterate over all variables
        for var, d in self.defs.items():
            i += 1
            defs = list(d)
            while len(defs) > 0:
                bb = defs.pop()
                for dom in self.dom.dominator_frontiers[bb]:
                    if has_already[dom] >= i:
                        continue

                    self._place_phi(var, dom)
                    has_already[dom] = i
                    if work[dom] < i:
                        work[dom] = i
                        defs.append(dom)

    def _place_phi(self, var: IRVariable, basic_block: IRBasicBlock):
        if var not in basic_block.liveness_in_vars:
            return

        args: list[IROperand] = []
        for bb in basic_block.cfg_in:
            if bb == basic_block:
                continue

            args.append(bb.label)  # type: ignore
            args.append(var)  # type: ignore

        basic_block.insert_instruction(IRInstruction("phi", args, var), 0)

    def _rename_vars(self, basic_block: IRBasicBlock):
        """
        Rename variables. This follows the placement of phi nodes.
        """
        outs = []

        # Pre-action
        for inst in basic_block.instructions:
            new_ops: list[IROperand] = []
            if inst.opcode != "phi":
                for op in inst.operands:
                    if not isinstance(op, IRVariable):
                        new_ops.append(op)
                        continue

                    new_ops.append(IRVariable(op.name, version=self.var_name_stacks[op.name][-1]))

                inst.operands = new_ops

            if inst.output is not None:
                v_name = inst.output.name
                i = self.var_name_counters[v_name]

                self.var_name_stacks[v_name].append(i)
                self.var_name_counters[v_name] = i + 1

                inst.output = IRVariable(v_name, version=i)
                # note - after previous line, inst.output.name != v_name
                outs.append(inst.output.name)

        for bb in basic_block.cfg_out:
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    continue
                assert inst.output is not None, "Phi instruction without output"
                for i, op in enumerate(inst.operands):
                    if op == basic_block.label:
                        inst.operands[i + 1] = IRVariable(
                            inst.output.name, version=self.var_name_stacks[inst.output.name][-1]
                        )

        for bb in self.dom.dominated[basic_block]:
            if bb == basic_block:
                continue
            self._rename_vars(bb)

        # Post-action
        for op_name in outs:
            # NOTE: each pop corresponds to an append in the pre-action above
            self.var_name_stacks[op_name].pop()

    def _remove_degenerate_phis(self, entry: IRBasicBlock):
        for inst in entry.instructions.copy():
            if inst.opcode != "phi":
                continue

            new_ops: list[IROperand] = []
            for label, op in inst.phi_operands:
                if op == inst.output:
                    continue
                new_ops.extend([label, op])
            new_ops_len = len(new_ops)
            if new_ops_len == 0:
                entry.instructions.remove(inst)
            elif new_ops_len == 2:
                entry.instructions.remove(inst)
            else:
                inst.operands = new_ops

        for bb in self.dom.dominated[entry]:
            if bb == entry:
                continue
            self._remove_degenerate_phis(bb)

    def _compute_defs(self):
        """
        Compute the definition points of variables in the function.
        """
        self.defs = {}
        for bb in self.dom.dfs_walk:
            assignments = bb.get_assignments()
            for var in assignments:
                if var not in self.defs:
                    self.defs[var] = OrderedSet()
                self.defs[var].add(bb)
