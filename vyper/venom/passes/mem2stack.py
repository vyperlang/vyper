from vyper.utils import OrderedSet
from vyper.venom.analysis import DFG, calculate_cfg, calculate_liveness
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class Mem2Stack(IRPass):
    """ """

    ctx: IRFunction
    dom: DominatorTree
    defs: dict[IRVariable, OrderedSet[IRBasicBlock]]
    dfg: DFG

    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock, dfg: DFG) -> int:
        self.ctx = ctx
        self.dfg = dfg

        calculate_cfg(ctx)
        self.dom = DominatorTree.build_dominator_tree(ctx, entry)
        # self._propagate_variables()
        dfg = DFG.build_dfg(ctx)
        self.dfg = dfg

        calculate_liveness(ctx)

        self.var_name_count = 0
        for var, inst in dfg.outputs.items():
            if inst.opcode != "alloca":
                continue
            self._process_alloca_var(dfg, var, inst)

        self._compute_stores()

        # self._rename_vars(entry)

        return 0

    def _propagate_variables(self):
        for bb in self.dom.dfs_walk:
            for inst in bb.instructions:
                if inst.opcode == "store":
                    uses = self.dfg.get_uses(inst.output)
                    remove_inst = True
                    for usage_inst in uses:
                        if usage_inst.opcode == "phi":
                            remove_inst = False
                            continue
                        for i, op in enumerate(usage_inst.operands):
                            if op == inst.output:
                                usage_inst.operands[i] = inst.operands[0]
                    if remove_inst:
                        inst.opcode = "nop"
                        inst.operands = []

    def _process_alloca_var(self, dfg: DFG, var: IRVariable, alloca_inst: IRInstruction):
        uses = dfg.get_uses(var)
        if all([inst.opcode == "mload" for inst in uses]):
            return
        elif all([inst.opcode == "mstore" for inst in uses]):
            return
        elif all([inst.opcode in ["mstore", "mload", "return"] for inst in uses]):
            var_name = f"addr{var.name}_{self.var_name_count}"
            self.var_name_count += 1
            # print(f"Processing alloca var {var_name}")
            # print(uses)
            for inst in uses:
                if inst.opcode == "mstore":
                    inst.opcode = "store"
                    inst.output = IRVariable(var_name)
                    inst.operands = [inst.operands[0]]
                elif inst.opcode == "mload":
                    inst.opcode = "store"
                    inst.operands = [IRVariable(var_name)]
                elif inst.opcode == "return":
                    bb = inst.parent
                    new_var = self.ctx.get_next_variable()
                    bb.insert_instruction(
                        IRInstruction("mstore", [IRVariable(var_name), inst.operands[1]], new_var),
                        -1,
                    )
                    inst.operands[1] = new_var

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
