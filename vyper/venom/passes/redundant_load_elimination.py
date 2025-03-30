from typing import Dict, Union

from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, DominatorTreeAnalysis, MemSSA
from vyper.venom.analysis.mem_ssa import MemoryDef, MemoryPhi, MemoryUse
from vyper.venom.basicblock import IRInstruction, IROperand
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class RedundantLoadElimination(IRPass):
    """
    This pass eliminates redundant memory loads using Memory SSA analysis
    """

    def __init__(self, analyses_cache, function):
        super().__init__(analyses_cache, function)
        self.replacements: Dict[IRInstruction, IROperand] = {}
        self.available_loads_per_block: Dict[any, Dict[MemoryUse, IROperand]] = {}

    def run_pass(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.mem_ssa = self.analyses_cache.request_analysis(MemSSA)
        self.updater = InstUpdater(self.dfg)

        rev_post_order = reversed(list(self.dom.dom_post_order))

        for bb in rev_post_order:
            self._process_block(bb)

        self._eliminate_redundant_loads()

    def _process_block(self, bb):
        available_loads = self._compute_available_loads_from_preds(bb)

        phi = self.mem_ssa.memory_phis.get(bb)
        if phi:
            for op_def, _ in phi.operands:
                if isinstance(op_def, MemoryDef):
                    available_loads = {
                        use: var
                        for use, var in available_loads.items()
                        if not self.mem_ssa.alias.may_alias(use.loc, op_def.loc)
                    }

        for inst in bb.instructions:
            mem_def = self.mem_ssa.get_memory_def(inst)
            mem_use = self.mem_ssa.get_memory_use(inst)

            if mem_def:
                available_loads = {
                    use: var
                    for use, var in available_loads.items()
                    if not self.mem_ssa.alias.may_alias(use.loc, mem_def.loc)
                }

            if mem_use and inst.opcode == "mload" and not mem_use.is_volatile:
                # Check for redundant loads
                for prev_use, prev_var in available_loads.items():
                    if (
                        prev_use.loc.completely_overlaps(mem_use.loc)
                        and not prev_use.is_volatile
                        and self._is_load_available(mem_use, prev_use.reaching_def)
                    ):
                        self.replacements[inst] = prev_var
                        break
                else:
                    available_loads[mem_use] = inst.output

        self.available_loads_per_block[bb] = available_loads

    def _compute_available_loads_from_preds(self, bb) -> Dict[MemoryUse, IROperand]:
        if not bb.cfg_in:  # Entry block
            return {}

        available_loads = {}
        first_pred = True

        for pred in bb.cfg_in:
            pred_loads = self.available_loads_per_block.get(pred, {})
            if first_pred:
                available_loads = pred_loads.copy()
                first_pred = False
            else:
                available_loads = {
                    use: var
                    for use, var in available_loads.items()
                    if use in pred_loads and pred_loads[use] == var
                }

        return available_loads

    def _eliminate_redundant_loads(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions.copy():
                if inst in self.replacements:
                    new_var = self.replacements[inst]
                    del self.mem_ssa.inst_to_use[inst]
                    self.updater.update(inst, "store", [new_var], "[redundant load elimination]")

    def _is_load_available(self, use: MemoryUse, reaching_def: Union[MemoryDef, MemoryPhi]) -> bool:
        if reaching_def.is_live_on_entry:
            return False

        def_loc = reaching_def.loc
        use_block = use.load_inst.parent

        if isinstance(reaching_def, MemoryDef):
            def_block = reaching_def.store_inst.parent
            if def_block == use_block:
                def_idx = def_block.instructions.index(reaching_def.store_inst)
                use_idx = use_block.instructions.index(use.load_inst)
                for inst in def_block.instructions[def_idx + 1 : use_idx]:
                    mem_def = self.mem_ssa.get_memory_def(inst)
                    if mem_def and self.mem_ssa.alias.may_alias(def_loc, mem_def.loc):
                        return False
            else:
                # Check inter-block path
                current = use.reaching_def
                while current and current != reaching_def and not current.is_live_on_entry:
                    if isinstance(current, MemoryDef) and self.mem_ssa.alias.may_alias(
                        def_loc, current.loc
                    ):
                        return False
                    current = current.reaching_def
        elif isinstance(reaching_def, MemoryPhi):
            phi_block = reaching_def.block
            if phi_block == use_block:
                use_idx = use_block.instructions.index(use.load_inst)
                for inst in use_block.instructions[:use_idx]:
                    mem_def = self.mem_ssa.get_memory_def(inst)
                    if mem_def and self.mem_ssa.alias.may_alias(def_loc, mem_def.loc):
                        return False
            else:
                # TODO: Inter-block phi case
                return False

        return True
