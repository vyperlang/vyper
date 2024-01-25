from vyper.utils import OrderedSet
from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IROperand, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class MakeSSA(IRPass):
    dom: DominatorTree
    defs: dict[IRVariable, OrderedSet[IRBasicBlock]]

    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock) -> int:
        self.ctx = ctx

        calculate_cfg(ctx)
        dom = DominatorTree(ctx, entry)
        self.dom = dom

        self._add_phi_nodes()

        self.var_names = {var.name: 0 for var in self.defs.keys()}
        self.stacks = {var.name: [0] for var in self.defs.keys()}
        self._rename_vars(entry)
        self._remove_degenerate_phis(entry)

        return 1

    def _add_phi_nodes(self):
        self._compute_defs()
        self.work = {var: 0 for var in self.dom.dfs}
        self.has_already = {var: 0 for var in self.dom.dfs}
        i = 0

        # Iterate over all variables
        for var, d in self.defs.items():
            i += 1
            defs = list(d)
            while len(defs) > 0:
                bb = defs.pop()
                for dom in self.dom.df[bb]:
                    if self.has_already[dom] >= i:
                        continue

                    self._place_phi(var, dom)
                    self.has_already[dom] = i
                    if self.work[dom] < i:
                        self.work[dom] = i
                        defs.append(dom)

    def _place_phi(self, var: IRVariable, basic_block: IRBasicBlock):
        args: list[IROperand] = []
        for bb in basic_block.cfg_in:
            if bb == basic_block:
                continue

            args.append(bb.label)  # type: ignore
            args.append(var)  # type: ignore

        phi = IRInstruction("phi", args, var)
        basic_block.instructions.insert(0, phi)

    def _add_phi(self, var: IRVariable, basic_block: IRBasicBlock) -> bool:
        for inst in basic_block.instructions:
            if inst.opcode == "phi" and inst.output is not None and inst.output.name == var.name:
                return False

        args: list[IROperand] = []
        for bb in basic_block.cfg_in:
            if bb == basic_block:
                continue

            args.append(bb.label)
            args.append(var)

        phi = IRInstruction("phi", args, var)
        basic_block.instructions.insert(0, phi)

        return True

    def _rename_vars(self, basic_block: IRBasicBlock):
        outs = []
        for inst in basic_block.instructions:
            new_ops = []
            if inst.opcode != "phi":
                for op in inst.operands:
                    if not isinstance(op, IRVariable):
                        new_ops.append(op)
                        continue

                    new_ops.append(IRVariable(op.name, version=self.stacks[op.name][-1]))

                inst.operands = new_ops

            if inst.output is not None:
                v_name = inst.output.name
                i = self.var_names[v_name]
                inst.output = IRVariable(v_name, version=i)
                outs.append(inst.output.name)
                self.stacks[v_name].append(i)
                self.var_names[v_name] = i + 1

        for bb in basic_block.cfg_out:
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    continue
                assert inst.output is not None, "Phi instruction without output"
                for i, op in enumerate(inst.operands):
                    if op == basic_block.label:
                        inst.operands[i + 1] = IRVariable(
                            inst.output.name, version=self.stacks[inst.output.name][-1]
                        )

        for bb in self.dom.dominated[basic_block]:
            if bb == basic_block:
                continue
            self._rename_vars(bb)

        for op_name in outs:
            self.stacks[op_name].pop()

    def __remove_degenerate_phis(self, entry: IRBasicBlock):
        for inst in entry.instructions:
            if inst.opcode != "phi":
                continue

            remove = False
            for _, var in inst.phi_operands:
                if var == inst.output:
                    remove = True
                    break

            if remove:
                entry.instructions.remove(inst)

        for bb in self.dom.dominated[entry]:
            if bb == entry:
                continue
            self._remove_degenerate_phis(bb)

    def _remove_degenerate_phis(self, entry: IRBasicBlock):
        for inst in entry.instructions:
            if inst.opcode != "phi":
                continue

            new_ops = []
            for label, op in inst.phi_operands:
                if op == inst.output:
                    continue
                new_ops.extend([label, op])
            new_ops_len = len(new_ops)
            if new_ops_len == 0:
                entry.instructions.remove(inst)
            elif new_ops_len == 2:
                inst.opcode = "store"
                inst.output = new_ops[1]
                inst.operands = [new_ops[0]]
            else:
                inst.operands = new_ops

        for bb in self.dom.dominated[entry]:
            if bb == entry:
                continue
            self._remove_degenerate_phis(bb)

    def _compute_defs(self):
        self.defs = {}
        for bb in self.dom.dfs:
            assignments = bb.get_assignments()
            for var in assignments:
                if var not in self.defs:
                    self.defs[var] = OrderedSet()
                self.defs[var].add(bb)
