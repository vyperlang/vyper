from vyper.utils import OrderedSet
from vyper.venom.analysis import DFG, calculate_cfg, calculate_liveness
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.dft import DFTPass


class Mem2Stack(IRPass):
    """ """

    dom: DominatorTree
    defs: dict[IRVariable, OrderedSet[IRBasicBlock]]

    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock, dfg: DFG) -> int:
        self.ctx = ctx

        calculate_cfg(ctx)
        self.dom = DominatorTree.build_dominator_tree(ctx, entry)

        calculate_liveness(ctx)

        self.var_name_count = 0
        for var, inst in dfg.outputs.items():
            if inst.opcode != "alloca":
                continue
            self._process_alloca_var(dfg, var, inst)

        self._compute_stores()

        # self._rename_vars(entry)

        return 0

    def _process_alloca_var(self, dfg: DFG, var: IRVariable, alloca_inst: IRInstruction):
        uses = dfg.get_uses(var)
        if all([inst.opcode == "mload" for inst in uses]):
            return
        elif all([inst.opcode == "mstore" for inst in uses]):
            return
        elif all([inst.opcode == "mstore" or inst.opcode == "mload" for inst in uses]):
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
