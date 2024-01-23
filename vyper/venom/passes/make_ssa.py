from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class MakeSSA(IRPass):
    dom: DominatorTree
    defs: dict[IRVariable, set[IRBasicBlock]]

    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock) -> int:
        self.ctx = ctx

        calculate_cfg(ctx)
        dom = DominatorTree(ctx, entry)
        self.dom = dom

        count = 0
        while self._add_phi_nodes():
            if count := count + 1 > len(ctx.basic_blocks) * 2:
                raise CompilerPanic("Failed to add phi nodes")

        self.var_names = {var.name: -1 for var in self.defs.keys()}
        self._rename_vars(entry, set())

        # print(ctx.as_graph())
        # import sys

        # sys.exit(0)

        self.changes = 0

    def _add_phi_nodes(self) -> bool:
        self._compute_defs()
        changed = False
        for var, defs in self.defs.items():
            for bb in defs:
                for front in self.dom.df[bb]:
                    changed |= self._add_phi(var, front)

        return changed

    def _rename_vars(self, basic_block: IRBasicBlock, visited: set):
        visited.add(basic_block)

        for inst in basic_block.instructions:
            new_ops = []
            for op in inst.operands:
                if not isinstance(op, IRVariable):
                    new_ops.append(op)
                    continue

                new_ops.append(IRVariable(op.name, version=self.var_names[op.name]))

            inst.operands = new_ops
            if inst.output is not None:
                self.var_names[inst.output.name] += 1
                inst.output = IRVariable(inst.output.name, version=self.var_names[inst.output.name])

        for bb in basic_block.cfg_out:
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    continue
                for i, op in enumerate(inst.operands):
                    if op == basic_block.label:
                        inst.operands[i + 1] = IRVariable(
                            inst.output.name, version=self.var_names[inst.output.name]
                        )

        for bb in self.dom.dominated[basic_block]:
            if bb in visited:
                continue
            self._rename_vars(bb, visited)

        for inst in basic_block.instructions:
            if inst.output is None:
                continue
            self.var_names[inst.output.name] -= 1

    def _add_phi(self, var: IRVariable, basic_block: IRBasicBlock) -> bool:
        for inst in basic_block.instructions:
            if inst.opcode == "phi" and inst.output.name == var.name:
                return False

        args = []
        for bb in basic_block.cfg_in:
            if bb == basic_block:
                continue

            args.append(bb.label)
            args.append(var)

        phi = IRInstruction("phi", args, var)
        basic_block.instructions.insert(0, phi)

        return True

    def _compute_defs(self):
        self.defs = {}
        for bb in self.dom.dfs:
            assignments = bb.get_assignments()
            for var in assignments:
                if var not in self.defs:
                    self.defs[var] = set()
                self.defs[var].add(bb)
