import pytest
from tests.venom_utils import parse_venom
from vyper.venom.analysis import MemoryAliasAnalysis, MemSSA, CFGAnalysis, DominatorTreeAnalysis
from vyper.venom.analysis.mem_ssa import MemoryDef, MemoryPhi
from vyper.venom.analysis.mem_alias import MemoryLocation
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.function import IRFunction
from vyper.venom.analysis import IRAnalysesCache
    
def test_basic_clobber():
    pre = """
    function _global {
        _global:
            mstore 0, %1
            %2 = mload 0
            stop
    }
    """

    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]
    
    ac = IRAnalysesCache(fn)

    mem_ssa = MemSSA(ac, fn)
    mem_ssa.analyze()
    
    mem_use = mem_ssa.memory_uses[fn.entry][0]
    
    # Test clobber detection
    clobbered = mem_ssa.get_clobbered_memory_access(mem_use)
    assert clobbered is not None
    assert isinstance(clobbered, MemoryDef)
    assert not clobbered.is_live_on_entry
    
    
def test_no_clobber_different_locations():
    pre = """
    function _global {
        _global:
            mstore 0, %1
            %2 = mload 32
            stop
    }
    """

    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]
    
    ac = IRAnalysesCache(fn)

    mem_ssa = MemSSA(ac, fn)
    mem_ssa.analyze()
    
    mem_use = mem_ssa.memory_uses[fn.entry][0]
    
    clobbered = mem_ssa.get_clobbered_memory_access(mem_use)
    assert clobbered.is_live_on_entry  # Should return live_on_entry since no clobber found

def test_phi_node_clobber():
    pre = """
    function _global {
        entry:
            jnz %1, @block1, @block2
        block1:
            mstore 0, %2
            jmp @merge
        block2:
            mstore 0, %3
            jmp @merge
        merge:
            %4 = mload 0
            stop
    }
    """

    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]
    
    ac = IRAnalysesCache(fn)

    mem_ssa = MemSSA(ac, fn)
    mem_ssa.analyze()
    
    merge_block = fn.get_basic_block("merge")
    mem_use = mem_ssa.memory_uses[merge_block][0]
    
    # Test clobber detection through phi node
    clobbered = mem_ssa.get_clobbered_memory_access(mem_use)
    assert clobbered is not None
    assert isinstance(clobbered, MemoryDef)
