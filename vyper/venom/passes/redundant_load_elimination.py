from typing import Dict, Union, List, Optional

from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, DominatorTreeAnalysis, MemSSA
from vyper.venom.analysis.mem_ssa import MemoryDef, MemoryPhi, MemoryUse
from vyper.venom.basicblock import IRInstruction, IROperand, IRBasicBlock
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class RedundantLoadElimination(IRPass):
    """
    This pass eliminates redundant memory loads using Memory SSA analysis.
    
    The optimization works by:
    1. Computing available loads at each basic block by merging loads from predecessors
    2. Tracking memory definitions that may kill available loads
    3. Identifying redundant loads that can be replaced with previously loaded values
    4. Ensuring load availability across control flow paths
    """

    def __init__(self, analyses_cache, function):
        super().__init__(analyses_cache, function)
        # Maps instructions to their replacement operands
        self.replacements: Dict[IRInstruction, IROperand] = {}
        # Maps basic blocks to their available loads
        self.available_loads_per_block: Dict[IRBasicBlock, Dict[MemoryUse, IROperand]] = {}

    def run_pass(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.mem_ssa = self.analyses_cache.request_analysis(MemSSA)
        self.updater = InstUpdater(self.dfg)

        # Pre-compute available loads for all blocks
        self._compute_available_loads()

        rev_post_order = reversed(list(self.dom.dom_post_order))
        for bb in rev_post_order:
            self._process_block(bb)

        self._eliminate_redundant_loads()

    def _compute_available_loads(self) -> None:
        for bb in self.dom.dom_post_order:
            if not bb.cfg_in:  # Entry block
                self.available_loads_per_block[bb] = {}
            else:
                idom = self.dom.immediate_dominator(bb)
                if not idom:
                    self.available_loads_per_block[bb] = {}
                else:
                    available_loads = self.available_loads_per_block.get(idom, {}).copy()

                    for pred in bb.cfg_in:
                        if pred == idom or self.dom.dominates(idom, pred):
                            continue
                            
                        pred_loads = self.available_loads_per_block.get(pred, {})
                        available_loads = {
                            use: var
                            for use, var in available_loads.items()
                            if use in pred_loads and pred_loads[use] == var
                        }

                    self.available_loads_per_block[bb] = available_loads

            current_loads = self.available_loads_per_block[bb].copy()
            for inst in bb.instructions:
                mem_def = self.mem_ssa.get_memory_def(inst)
                mem_use = self.mem_ssa.get_memory_use(inst)

                if mem_def:
                    current_loads = {
                        use: var
                        for use, var in current_loads.items()
                        if not self.mem_ssa.alias.may_alias(use.loc, mem_def.loc)
                    }

                if mem_use and inst.opcode == "mload" and not mem_use.is_volatile:
                    current_loads[mem_use] = inst.output

            self.available_loads_per_block[bb] = current_loads

    def _process_block(self, bb: IRBasicBlock) -> None:
        available_loads = self.available_loads_per_block[bb].copy()

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
                for use, var in available_loads.items():
                    if (
                        use.loc.completely_overlaps(mem_use.loc)
                        and not use.is_volatile
                        and self._is_load_available(mem_use, use.reaching_def)
                    ):
                        self.replacements[inst] = var
                        break
                else:
                    available_loads[mem_use] = inst.output

        self.available_loads_per_block[bb] = available_loads

    def _eliminate_redundant_loads(self) -> None:
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions.copy():
                if inst in self.replacements:
                    new_var = self.replacements[inst]
                    del self.mem_ssa.inst_to_use[inst]
                    self.updater.update(inst, "store", [new_var], "[redundant load elimination]")

    def _is_load_available(self, use: MemoryUse, last_memory_write: Union[MemoryDef, MemoryPhi]) -> bool:
        """
        Check if a load is available at a use point.
        """
        if last_memory_write.is_live_on_entry:
            return False

        def_loc = last_memory_write.loc
        use_block = use.load_inst.parent

        if isinstance(last_memory_write, MemoryDef):
            def_block = last_memory_write.store_inst.parent
            if def_block == use_block:
                def_idx = def_block.instructions.index(last_memory_write.store_inst)
                use_idx = use_block.instructions.index(use.load_inst)
                for inst in def_block.instructions[def_idx + 1 : use_idx]:
                    mem_def = self.mem_ssa.get_memory_def(inst)
                    if mem_def and self.mem_ssa.alias.may_alias(def_loc, mem_def.loc):
                        return False
            else:
                # Check inter-block path
                current = use.reaching_def
                while current and current != last_memory_write and not current.is_live_on_entry:
                    if isinstance(current, MemoryDef) and self.mem_ssa.alias.may_alias(
                        def_loc, current.loc
                    ):
                        return False
                    current = current.reaching_def
        elif isinstance(last_memory_write, MemoryPhi):
            return False

        return True
