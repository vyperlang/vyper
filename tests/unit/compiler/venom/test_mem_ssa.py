from tests.venom_utils import parse_venom
from vyper.venom.analysis import IRAnalysesCache, MemSSA
from vyper.venom.analysis.mem_ssa import MemoryDef, MemoryPhi, MemoryUse
from vyper.venom.basicblock import IRLabel


def test_basic_clobber():
    pre = """
    function _global {
        _global:
            %val = 42
            mstore 0, %val
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
    # Verify it's the store instruction in the entry block
    assert clobbered.loc.offset == 0
    assert clobbered.store_inst.operands[0].value == "%val"
    assert clobbered.store_inst.parent == fn.entry


def test_no_clobber_different_locations():
    pre = """
    function _global {
        _global:
            %val = 1
            mstore 0, %val
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
            %cond_val = 10
            mstore 64, %cond_val
            %cond = mload 64
            jnz %cond, @block1, @block2
        block1:
            %val1 = 42
            mstore 0, %val1
            jmp @merge
        block2:
            %val2 = 24
            mstore 0, %val2
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
    # Verify it's a phi node with both store instructions
    assert clobbered.loc.offset == 0
    block1 = fn.get_basic_block("block1")
    block2 = fn.get_basic_block("block2")
    block1_def = mem_ssa.memory_defs[block1][0]
    block2_def = mem_ssa.memory_defs[block2][0]
    assert block1_def.store_inst.operands[0].value == "%val1"
    assert block2_def.store_inst.operands[0].value == "%val2"


def test_complex_loop_clobber():
    pre = """
    function _global {
        entry:
            %init_val = 10
            mstore 0, %init_val          # Initial store
            jmp @loop_header
        loop_header:
            %loop_val = mload 0          # Load that could be clobbered by multiple paths
            %cond1_val = 1
            mstore 96, %cond1_val        # Store first condition
            %cond1 = mload 96            # Load first condition
            jnz %cond1, @path_a, @path_b
        path_a:
            %cond2_val = 1
            mstore 128, %cond2_val       # Store second condition
            %cond2 = mload 128           # Load second condition
            jnz %cond2, @nested_a1, @nested_a2
        nested_a1:
            %val_a1 = 42
            mstore 0, %val_a1            # Potential clobber 1
            jmp @loop_continue
        nested_a2:
            %val_a2 = 24
            mstore 32, %val_a2           # Store to different location
            jmp @loop_continue
        path_b:
            %val_b = 84
            mstore 0, %val_b             # Potential clobber 2
            jmp @loop_continue
        loop_continue:
            %loop_cond_val = 1
            mstore 160, %loop_cond_val   # Store loop condition
            %loop_cond = mload 160       # Load loop condition
            jnz %loop_cond, @loop_header, @exit
        exit:
            %final = mload 0
            stop
    }
    """

    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]

    ac = IRAnalysesCache(fn)
    mem_ssa = MemSSA(ac, fn)
    mem_ssa.analyze()

    # Test the load in loop_header
    loop_header_block = fn.get_basic_block("loop_header")
    loop_header_load = mem_ssa.memory_uses[loop_header_block][0]
    clobbered = mem_ssa.get_clobbered_memory_access(loop_header_load)

    # Should detect clobbering since the load can be affected by stores in nested_a1 and path_b
    assert clobbered is not None
    assert isinstance(clobbered, MemoryDef)
    assert not clobbered.is_live_on_entry

    # Verify the clobbering comes from the correct stores
    nested_a1_block = fn.get_basic_block("nested_a1")
    path_b_block = fn.get_basic_block("path_b")
    nested_a1_def = mem_ssa.memory_defs[nested_a1_block][0]
    path_b_def = mem_ssa.memory_defs[path_b_block][0]

    assert nested_a1_def.loc.offset == 0
    assert nested_a1_def.store_inst.operands[0].value == "%val_a1"
    assert path_b_def.loc.offset == 0
    assert path_b_def.store_inst.operands[0].value == "%val_b"

    # Test the final load in exit block
    exit_block = fn.get_basic_block("exit")
    exit_load = mem_ssa.memory_uses[exit_block][0]
    exit_clobbered = mem_ssa.get_clobbered_memory_access(exit_load)

    # Should also detect clobbering for the final load
    assert exit_clobbered is not None
    assert isinstance(exit_clobbered, MemoryDef)
    assert not exit_clobbered.is_live_on_entry

    # Verify store to different location doesn't affect analysis
    nested_a2_block = fn.get_basic_block("nested_a2")
    different_loc_store = mem_ssa.memory_defs[nested_a2_block][0]
    assert different_loc_store.loc.offset == 32
    assert different_loc_store.store_inst.operands[0].value == "%val_a2"


def test_simple_def_chain():
    code = """
    function _global {
        entry:
            %val1 = 10
            mstore 0, %val1
            %val2 = 20
            mstore 0, %val2
            %val3 = 30
            mstore 0, %val3
            %val4 = mload 0
            stop
    }
    """

    ctx = parse_venom(code)
    fn = ctx.functions[IRLabel("_global")]

    ac = IRAnalysesCache(fn)
    mem_ssa = MemSSA(ac, fn)
    mem_ssa.analyze()

    bb = fn.get_basic_block("entry")
    def_1 = mem_ssa.get_memory_def(bb.instructions[1])
    def_2 = mem_ssa.get_memory_def(bb.instructions[3])
    def_3 = mem_ssa.get_memory_def(bb.instructions[5])
    use_loc0 = mem_ssa.get_memory_use(bb.instructions[-2])
    
    assert use_loc0 is not None
    assert isinstance(use_loc0, MemoryUse)
    assert use_loc0.loc.offset == 0
    assert use_loc0.reaching_def == def_3
    assert def_3.reaching_def == def_2
    assert def_2.reaching_def == def_1
    assert def_1.reaching_def == mem_ssa.live_on_entry


