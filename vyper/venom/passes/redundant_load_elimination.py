from typing import Optional, Dict

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, MemSSA
from vyper.venom.analysis.mem_ssa import MemoryDef, MemoryUse
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IROperand
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class RedundantLoadElimination(IRPass):
    """
    This pass eliminates redundant memory loads using Memory SSA analysis
    """

    def __init__(self, analyses_cache, function):
        super().__init__(analyses_cache, function)
        self.replacements: Dict[
            IRInstruction, IROperand
        ] = {}

    def run_pass(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.mem_ssa = self.analyses_cache.request_analysis(MemSSA)
        self.updater = InstUpdater(self.dfg)

        self._identify_redundant_loads()
        self._eliminate_redundant_loads()

    def _identify_redundant_loads(self):
        available_loads: Dict[MemoryUse, IROperand] = {}  # MemoryUse -> output operand

        for bb in self.cfg.dfs_pre_walk:
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

                if mem_use and inst.opcode == "mload":
                    for prev_use, prev_var in list(available_loads.items()):
                        if (
                            prev_use.loc.completely_overlaps(mem_use.loc)
                            and not mem_use.is_volatile
                            and not prev_use.is_volatile
                        ):
                            self.replacements[inst] = prev_var
                            break

                    if inst not in self.replacements and not mem_use.is_volatile:
                        available_loads[mem_use] = inst.output  # Use output member as IROperand

            for succ in bb.cfg_out:
                succ_phi = self.mem_ssa.memory_phis.get(succ)
                if succ_phi:
                    for op_def, pred in succ_phi.operands:
                        if pred == bb and isinstance(op_def, MemoryDef):
                            available_loads = {
                                use: var
                                for use, var in available_loads.items()
                                if not self.mem_ssa.alias.may_alias(use.loc, op_def.loc)
                            }

    def _eliminate_redundant_loads(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions[:]:  # Copy list to modify during iteration
                if inst in self.replacements:
                    new_var = self.replacements[inst]
                    del self.mem_ssa.inst_to_use[inst]

                    self.updater.update(inst, "store", [new_var], "[redundant load elimination]")

    def _is_load_available(self, use: MemoryUse, reaching_def: MemoryDef) -> bool:
        if reaching_def.is_live_on_entry:
            return False

        def_loc = reaching_def.loc
        def_block = reaching_def.store_inst.parent
        use_block = use.load_inst.parent

        if def_block == use_block:
            def_idx = def_block.instructions.index(reaching_def.store_inst)
            use_idx = use_block.instructions.index(use.load_inst)
            for inst in def_block.instructions[def_idx + 1 : use_idx]:
                mem_def = self.mem_ssa.get_memory_def(inst)
                if mem_def and self.mem_ssa.alias.may_alias(def_loc, mem_def.loc):
                    return False
        else:
            current = use.reaching_def
            while current and current != reaching_def and not current.is_live_on_entry:
                if isinstance(current, MemoryDef) and self.mem_ssa.alias.may_alias(
                    def_loc, current.loc
                ):
                    return False
                current = current.reaching_def

        return True
