from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, DominatorTreeAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IROperand, IRVariable
from vyper.venom.passes.base_pass import IRPass


class MakeSSA(IRPass):
    """
    This pass converts the function into Static Single Assignment (SSA) form.
    """

    dom: DominatorTreeAnalysis
    cfg: CFGAnalysis
    liveness: LivenessAnalysis
    defs: dict[IRVariable, OrderedSet[IRBasicBlock]]
    used_var_names: set[str]
    var_name_counters: dict[IRVariable, int]
    var_name_stacks: dict[IRVariable, list[IRVariable]]

    def run_pass(self):
        fn = self.function

        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)

        self.liveness = self.analyses_cache.request_analysis(LivenessAnalysis)

        self._add_phi_nodes()

        self.used_var_names = self._collect_used_var_names()
        self.var_name_counters = {var: 0 for var in self.defs.keys()}
        self.var_name_stacks = {var: [var] for var in self.defs.keys()}
        self._rename_vars(fn.entry)
        self._remove_degenerate_phis(fn.entry)

        # Ensure phis remain at top of blocks after converting some to stores
        for bb in fn.get_basic_blocks():
            bb.ensure_well_formed()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _add_phi_nodes(self):
        """
        Add phi nodes to the function.
        """
        self._compute_defs()
        work = {bb: 0 for bb in self.dom.dom_post_order}
        has_already = {bb: 0 for bb in self.dom.dom_post_order}
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
        if var not in self.liveness.liveness_in_vars(basic_block):
            return

        args: list[IROperand] = []
        for bb in self.cfg.cfg_in(basic_block):
            args.append(bb.label)
            args.append(var)

        basic_block.insert_instruction(IRInstruction("phi", args, [var]), 0)

    def _collect_used_var_names(self) -> set[str]:
        names: set[str] = set()
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                for out in inst.get_outputs():
                    names.add(out.value)
                for op in inst.operands:
                    if isinstance(op, IRVariable):
                        names.add(op.value)
        return names

    def _next_var_version(self, var: IRVariable) -> IRVariable:
        version = self.var_name_counters[var]
        if version == 0:
            self.var_name_counters[var] = 1
            return var

        while True:
            candidate = f"{var.name}:{version}"
            version += 1
            if candidate not in self.used_var_names:
                self.var_name_counters[var] = version
                self.used_var_names.add(candidate)
                return IRVariable(candidate)

    def latest_version_of(self, var: IRVariable) -> IRVariable:
        return self.var_name_stacks[var][-1]

    def _rename_vars(self, basic_block: IRBasicBlock):
        """
        Rename variables. This follows the placement of phi nodes.
        """
        outs: list[IRVariable] = []

        # Pre-action
        for inst in basic_block.instructions:
            new_ops: list[IROperand] = []
            if inst.opcode != "phi":
                for op in inst.operands:
                    if not isinstance(op, IRVariable):
                        new_ops.append(op)
                        continue

                    op = self.latest_version_of(op)
                    new_ops.append(op)

                inst.operands = new_ops

            outputs = inst.get_outputs()
            if len(outputs) == 0:
                continue

            new_outputs: list[IRVariable] = []
            for output in outputs:
                new_var = self._next_var_version(output)
                self.var_name_stacks[output].append(new_var)
                new_outputs.append(new_var)
                outs.append(output)

            inst.set_outputs(new_outputs)

        for bb in self.cfg.cfg_out(basic_block):
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    continue
                # Ensure phi has exactly one output
                _ = inst.output
                for i, op in enumerate(inst.operands):
                    if op == basic_block.label:
                        var = inst.operands[i + 1]
                        if isinstance(var, IRVariable):
                            inst.operands[i + 1] = self.latest_version_of(var)

        for bb in self.dom.dominated[basic_block]:
            if bb == basic_block:
                continue
            self._rename_vars(bb)

        # Post-action
        for var in outs:
            # NOTE: each pop corresponds to an append in the pre-action above
            self.var_name_stacks[var].pop()

    def _remove_degenerate_phis(self, entry: IRBasicBlock):
        for inst in entry.instructions.copy():
            if inst.opcode != "phi":
                continue

            new_ops: list[IROperand] = []
            phi_out = inst.output
            for label, op in inst.phi_operands:
                if op == phi_out:
                    continue
                new_ops.extend([label, op])
            new_ops_len = len(new_ops)
            if new_ops_len == 0:
                entry.instructions.remove(inst)
            elif new_ops_len == 2:
                # Single incoming value - convert to assign to preserve uses
                inst.opcode = "assign"
                inst.operands = [new_ops[1]]  # new_ops is [label, value]
            else:
                # Check if all operands have the same value (can simplify to assign)
                # new_ops is [label1, val1, label2, val2, ...]
                values = new_ops[1::2]  # extract values at odd indices
                if len(set(values)) == 1:
                    inst.opcode = "assign"
                    inst.operands = [values[0]]
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
        for bb in self.dom.dom_post_order:
            assignments = bb.get_assignments()
            for var in assignments:
                if var not in self.defs:
                    self.defs[var] = OrderedSet()
                self.defs[var].add(bb)
