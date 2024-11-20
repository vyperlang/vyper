
from analysis.mem_alias import MemoryAliasAnalysis
from vyper.venom.analysis import DFGAnalysis
from vyper.venom.passes.base_pass import IRPass

class MemoryAliasPass(IRPass):
    """
    Pass that uses memory alias analysis to optimize memory operations.
    Currently focuses on identifying non-aliasing memory operations
    that can be safely reordered or optimized.
    """

    def run_pass(self):
        # Request memory alias analysis
        alias_analysis = self.analyses_cache.request_analysis(MemoryAliasAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        # Look for optimization opportunities
        for bb in self.function.get_basic_blocks():
            self._optimize_basic_block(bb, alias_analysis, dfg)

        # Invalidate analyses that may be affected
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _optimize_basic_block(self, bb, alias_analysis, dfg):
        """Optimize memory operations in a basic block"""
        for i, inst in enumerate(bb.instructions):
            if inst.opcode != "mload":
                continue
                
            # Look for mload after mstore to same location
            store_inst = self._find_previous_store(inst, bb.instructions[:i], alias_analysis)
            if store_inst is not None:
                # Replace mload with stored value
                inst.opcode = "store" 
                inst.operands = [store_inst.operands[1]]

    def _find_previous_store(self, load_inst, prev_insts, alias_analysis):
        """Find most recent store that must write to same location as load"""
        load_addr = load_inst.operands[0]
        
        for inst in reversed(prev_insts):
            if inst.opcode != "mstore":
                continue
                
            store_addr = inst.operands[1]
            
            if load_addr == store_addr:
                return inst
                
            if not alias_analysis.may_alias(load_inst, inst):
                continue
                
            return None
            
        return None