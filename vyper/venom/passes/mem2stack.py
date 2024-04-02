from vyper.utils import OrderedSet
from vyper.venom.analysis import calculate_cfg, calculate_liveness
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class Mem2Stack(IRPass):
    """
    """

    dom: DominatorTree
    defs: dict[IRVariable, OrderedSet[IRBasicBlock]]

    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock) -> int:
        self.ctx = ctx

        calculate_cfg(ctx)
        self.dom = DominatorTree.build_dominator_tree(ctx, entry)

        calculate_liveness(ctx)
        
        self._compute_stores()

        self.var_name_counters = {var: 0 for var in self.defs.keys()}
        self.var_name_stacks = {var: [0] for var in self.defs.keys()}
        self._rename_vars(entry)
        
        return 0

    def _rename_vars(self, basic_block: IRBasicBlock):
        outs = []

        # Pre-action
        for inst in basic_block.instructions:
            if self._is_store(inst):
                v_name = f"addr{inst.operands[1]}"
                i = self.var_name_counters[v_name]

                self.var_name_stacks[v_name].append(i)
                self.var_name_counters[v_name] = i + 1

                outs.append(inst.operands[1])
                inst.opcode = "store"
                inst.output = IRVariable(v_name, version=i)
                inst.operands = [inst.operands[0]]

        # for bb in basic_block.cfg_out:
        #     for inst in bb.instructions:
        #         if inst.opcode != "phi":
        #             continue
        #         assert inst.output is not None, "Phi instruction without output"
        #         for i, op in enumerate(inst.operands):
        #             if op == basic_block.label:
        #                 inst.operands[i + 1] = IRVariable(
        #                     inst.output.name, version=self.var_name_stacks[inst.output.name][-1]
        #                 )

        for bb in self.dom.dominated[basic_block]:
            if bb == basic_block:
                continue
            self._rename_vars(bb)

        # Post-action
        for op_name in outs:
            # NOTE: each pop corresponds to an append in the pre-action above
            self.var_name_stacks[f"addr{op_name}"].pop()

    def _compute_stores(self):
        self.defs = {}
        for bb in self.dom.dfs_walk:
            for inst in bb.instructions:
                if self._is_store(inst):
                  var = f"addr{inst.operands[1]}"
                  if var not in self.defs:
                      self.defs[var] = OrderedSet()
                  self.defs[var].add(bb)

    def _is_store(self, inst: IRInstruction) -> bool:
        return inst.opcode == "mstore" and isinstance(inst.operands[1], IRLiteral)
    
    def _is_load(self, inst: IRInstruction) -> bool:
        return inst.opcode == "mload" and isinstance(inst.operands[0], IRLiteral)
