from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class MakeSSA(IRPass):
    dom: DominatorTree
    defs: dict[IRVariable, set[IRBasicBlock]]

    def _run_pass(self, ctx: IRFunction) -> int:
        self.ctx = ctx

        calculate_cfg(ctx)
        entry = ctx.get_basic_block(ctx.entry_points[0].value)
        dom = DominatorTree(ctx, entry)
        self.dom = dom

        self._compute_defs()
        self._add_phi_nodes()

        self.var_names = {var.name: 0 for var in self.defs.keys()}
        self._rename_vars(entry, set())

        print(ctx.as_graph())

        self.changes = 0

    def _add_phi_nodes(self):
        for var, defs in self.defs.items():
            for bb in defs:
                for front in self.dom.df[bb]:
                    self._add_phi(var, front)

    def _rename_vars(self, basic_block: IRBasicBlock, visited: set):
        visited.add(basic_block)

        for inst in basic_block.instructions:
            if inst.output is None:
                continue

            inst.replace_operands(
                {inst.output: IRVariable(f"{inst.output.name}{self.var_names[inst.output.name]}")}
            )
            self.var_names[inst.output.name] += 1
            inst.output = IRVariable(f"{inst.output.value}{self.var_names[inst.output.name]}")

        for bb in basic_block.cfg_out:
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    continue
                for i, op in enumerate(inst.operands):
                    if op == basic_block.label:
                        inst.operands[i + 1] = IRVariable(
                            f"{inst.output.name}{self.var_names[inst.output.name]}"
                        )

        for bb in self.dom.dominated[basic_block]:
            if bb in visited:
                continue
            self._rename_vars(bb, visited)

        for inst in basic_block.instructions:
            if inst.output is None:
                continue
            self.var_names[inst.output.name] -= 1

    def _add_phi(self, var: IRVariable, basic_block: IRBasicBlock):
        # TODO: check if the phi already exists
        args = []
        for bb in basic_block.cfg_in:
            if bb == basic_block:
                continue
            args.append(bb.label)
            args.append(var)

        phi = IRInstruction("phi", args, var)
        basic_block.instructions.insert(0, phi)

    def _compute_defs(self):
        self.defs = {}
        for bb in self.dom.dfs:
            assignments = bb.get_assignments()
            for var in assignments:
                if var not in self.defs:
                    self.defs[var] = set()
                self.defs[var].add(bb)
