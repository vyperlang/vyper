import pytest

from tests.venom_utils import parse_venom
from vyper.evm.address_space import MEMORY, STORAGE, AddrSpace
from vyper.venom.analysis import IRAnalysesCache, MemSSA
from vyper.venom.analysis.mem_ssa import (
    MemoryAccess,
    MemoryDef,
    MemoryLocation,
    MemoryPhi,
    MemoryUse,
    StorageSSA,
)
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.effects import Effects


@pytest.fixture
def dummy_mem_ssa():
    """Fixture that creates a MemSSA instance from a simple function."""
    pre = """
    function _global {
        entry:
            stop
    }
    """
    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]
    ac = IRAnalysesCache(fn)
    mem_ssa = MemSSA(ac, fn)
    mem_ssa.analyze()
    return mem_ssa, fn, ctx


def _create_mem_ssa(code, addr_space: AddrSpace, function_name="_global"):
    """Fixture that creates a MemSSA instance from custom code."""
    ctx = parse_venom(code)
    fn = ctx.functions[IRLabel(function_name)]
    ac = IRAnalysesCache(fn)
    if addr_space == MEMORY:
        mem_ssa = MemSSA(ac, fn)
    else:
        mem_ssa = StorageSSA(ac, fn)
    mem_ssa.analyze()
    return mem_ssa, fn, ctx


def create_mem_ssa(code, function_name="_global"):
    return _create_mem_ssa(code, addr_space=MEMORY, function_name=function_name)


def create_storage_ssa(code, function_name="_global"):
    return _create_mem_ssa(code, addr_space=STORAGE, function_name=function_name)


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

    mem_ssa, fn, _ = create_mem_ssa(pre)
    mem_use = mem_ssa.memory_uses[fn.entry][0]

    # Test clobber detection
    clobbered = mem_ssa.get_clobbered_memory_access(mem_use)
    assert clobbered is not None
    assert isinstance(clobbered, MemoryDef)
    assert not clobbered.is_live_on_entry
    # Verify it's the store instruction in the entry block
    assert clobbered.loc.offset == 0
    assert clobbered.inst.operands[0].value == "%val"
    assert clobbered.inst.parent == fn.entry


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

    mem_ssa, fn, _ = create_mem_ssa(pre)
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

    mem_ssa, fn, _ = create_mem_ssa(pre)
    merge_block = fn.get_basic_block("merge")
    mem_use = mem_ssa.memory_uses[merge_block][0]

    # Test clobber detection through phi node
    clobbered = mem_ssa.get_clobbered_memory_access(mem_use)
    assert clobbered is not None
    assert isinstance(clobbered, MemoryPhi)

    # Verify it's a phi node with both store instructions
    assert clobbered.loc.offset == 0
    block1 = fn.get_basic_block("block1")
    block2 = fn.get_basic_block("block2")
    block1_def = mem_ssa.memory_defs[block1][0]
    block2_def = mem_ssa.memory_defs[block2][0]
    assert block1_def.inst.operands[0].value == "%val1"
    assert block2_def.inst.operands[0].value == "%val2"


def test_partially_overlapping_clobber():
    pre = """
    function _global {
        _global:
            %1 = source
            mstore 256, 4     ; def: 3 (live_on_entry)
            mstore 288, 1007
            mstore 352, 1007
            mstore 356, %1
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    # Get the block and instructions
    bb = fn.get_basic_block("_global")
    store1 = bb.instructions[1]
    store2 = bb.instructions[2]
    store3 = bb.instructions[3]
    store4 = bb.instructions[4]

    # Check definitions
    def1 = mem_ssa.get_memory_def(store1)
    def2 = mem_ssa.get_memory_def(store2)
    def3 = mem_ssa.get_memory_def(store3)
    def4 = mem_ssa.get_memory_def(store4)

    assert def1 is not None, "Should have a memory definition for store1"
    assert def2 is not None, "Should have a memory definition for store2"
    assert def3 is not None, "Should have a memory definition for store3"
    assert def4 is not None, "Should have a memory definition for store4"

    # Verify partial overlap detection
    assert mem_ssa.memalias.may_alias(
        def3.loc, def4.loc
    ), "Partially overlapping locations should alias"


def test_ambiguous_clobber():
    pre = """
    function _global {
    _global:
        %6 = callvalue
        mstore 192, 32
        mstore 64, 5
        calldatacopy %6, 0, 32
        return 192, 32
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    # Get the block and instructions
    bb = fn.get_basic_block("_global")
    store1 = bb.instructions[1]  # mstore 192, 32
    store2 = bb.instructions[2]  # mstore 64, 5
    calldatacopy = bb.instructions[3]  # calldatacopy %6, 0, 32

    # Check definitions
    def1 = mem_ssa.get_memory_def(store1)
    def2 = mem_ssa.get_memory_def(store2)
    calldatacopy_def = mem_ssa.get_memory_def(calldatacopy)

    assert def1 is not None, "Should have a memory definition for store1"
    assert def2 is not None, "Should have a memory definition for store2"
    assert calldatacopy_def is not None, "Should have a memory definition for calldatacopy"

    # Verify calldatacopy returns FULL_MEMORY_ACCESS
    assert (
        calldatacopy_def.loc.offset is None and calldatacopy_def.loc.size == 32
    ), f"Expected unknown offset and size == 32 for calldatacopy, got {calldatacopy_def.loc}"


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

    mem_ssa, fn, _ = create_mem_ssa(pre)

    # Test the load in loop_header
    loop_header_block = fn.get_basic_block("loop_header")
    loop_header_load = mem_ssa.memory_uses[loop_header_block][0]
    clobbered = mem_ssa.get_clobbered_memory_access(loop_header_load)

    # Should detect clobbering since the load can be affected by stores in nested_a1 and path_b
    assert clobbered is not None
    assert isinstance(clobbered, MemoryPhi)
    assert not clobbered.is_live_on_entry

    # Verify the clobbering comes from the correct stores
    nested_a1_block = fn.get_basic_block("nested_a1")
    path_b_block = fn.get_basic_block("path_b")
    nested_a1_def = mem_ssa.memory_defs[nested_a1_block][0]
    path_b_def = mem_ssa.memory_defs[path_b_block][0]

    assert nested_a1_def.loc.offset == 0
    assert nested_a1_def.inst.operands[0].value == "%val_a1"
    assert path_b_def.loc.offset == 0
    assert path_b_def.inst.operands[0].value == "%val_b"

    # Test the final load in exit block
    exit_block = fn.get_basic_block("exit")
    exit_load = mem_ssa.memory_uses[exit_block][0]
    exit_clobbered = mem_ssa.get_clobbered_memory_access(exit_load)

    # Should also detect clobbering for the final load
    assert exit_clobbered is not None
    assert isinstance(exit_clobbered, MemoryPhi)
    assert not exit_clobbered.is_live_on_entry

    # Verify store to different location doesn't affect analysis
    nested_a2_block = fn.get_basic_block("nested_a2")
    different_loc_store = mem_ssa.memory_defs[nested_a2_block][0]
    assert different_loc_store.loc.offset == 32
    assert different_loc_store.inst.operands[0].value == "%val_a2"


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

    mem_ssa, fn, _ = create_mem_ssa(code)

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


def test_may_alias(dummy_mem_ssa):
    mem_ssa, _, _ = dummy_mem_ssa

    # Test non-overlapping memory locations
    loc1 = MemoryLocation(offset=0, size=32)
    loc2 = MemoryLocation(offset=32, size=32)
    assert not mem_ssa.memalias.may_alias(loc1, loc2), "Non-overlapping locations should not alias"

    # Test overlapping memory locations
    loc3 = MemoryLocation(offset=0, size=16)
    loc4 = MemoryLocation(offset=8, size=8)
    assert mem_ssa.memalias.may_alias(loc3, loc4), "Overlapping locations should alias"

    full_loc = MemoryLocation(offset=0, size=None)
    assert mem_ssa.memalias.may_alias(full_loc, loc1), "should alias with any non-empty location"
    assert not mem_ssa.memalias.may_alias(
        full_loc, MemoryLocation.EMPTY
    ), "should not alias with EMPTY_MEMORY_ACCESS"

    # Test EMPTY_MEMORY_ACCESS
    empty_loc = MemoryLocation.EMPTY
    assert not mem_ssa.memalias.may_alias(
        empty_loc, loc1
    ), "EMPTY_MEMORY_ACCESS should not alias with any location"
    assert not mem_ssa.memalias.may_alias(
        empty_loc, full_loc
    ), "EMPTY_MEMORY_ACCESS should not alias"

    # Test zero/negative size locations
    zero_size_loc = MemoryLocation(offset=0, size=0)
    assert not mem_ssa.memalias.may_alias(
        zero_size_loc, loc1
    ), "Zero size location should not alias"
    assert not mem_ssa.memalias.may_alias(
        zero_size_loc, zero_size_loc
    ), "Zero size locations should not alias with each other"

    # Test partial overlap
    loc5 = MemoryLocation(offset=0, size=64)
    loc6 = MemoryLocation(offset=32, size=32)
    assert mem_ssa.memalias.may_alias(loc5, loc6), "Partially overlapping locations should alias"
    assert mem_ssa.memalias.may_alias(loc6, loc5), "Partially overlapping locations should alias"

    # Test exact same location
    loc7 = MemoryLocation(offset=0, size=64)
    loc8 = MemoryLocation(offset=0, size=64)
    assert mem_ssa.memalias.may_alias(loc7, loc8), "Identical locations should alias"

    # Test adjacent but non-overlapping locations
    loc9 = MemoryLocation(offset=0, size=64)
    loc10 = MemoryLocation(offset=64, size=64)
    assert not mem_ssa.memalias.may_alias(
        loc9, loc10
    ), "Adjacent but non-overlapping locations should not alias"
    assert not mem_ssa.memalias.may_alias(
        loc10, loc9
    ), "Adjacent but non-overlapping locations should not alias"


def test_basic_def_use_assignment():
    pre = """
    function _global {
        _global:
            %1 = source
            mstore 0, 1
            mstore 32, 2
            %2 = mload 0
            stop
    }
    """

    mem_ssa, fn, _ = create_mem_ssa(pre)

    # Get the block and instructions
    bb = fn.get_basic_block("_global")
    store1 = bb.instructions[1]  # mstore 0, 1
    store2 = bb.instructions[2]  # mstore 32, 2
    load = bb.instructions[3]  # %2 = mload 0

    # Check definitions
    def1 = mem_ssa.get_memory_def(store1)
    def2 = mem_ssa.get_memory_def(store2)
    assert def1 is not None
    assert def2 is not None
    assert def1.id == 1
    assert def2.id == 2
    assert def1.loc.offset == 0
    assert def2.loc.offset == 32

    # Check use
    use = mem_ssa.get_memory_use(load)
    assert use is not None
    assert use.reaching_def == def2
    assert use.loc.offset == 0

    # Verify the def chain
    assert def1.reaching_def == mem_ssa.live_on_entry
    assert def2.reaching_def == def1


def test_read_write_memory_clobbering():
    pre = """
    function _global {
        entry:
            mstore 0, 42        # Store value at 0
            mstore 32, 100         # Store value at 32
            %ret = call 0, 0x1234, 0, 0, 32, 32, 32
            %loaded = mload 0       # Load from 0
            %loaded2 = mload 32     # Load from 32
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    # Get the block and instructions
    bb = fn.get_basic_block("entry")
    store1 = bb.instructions[0]  # mstore 0, %value
    store2 = bb.instructions[1]  # mstore 32, 100
    call_inst = bb.instructions[2]  # call instruction
    load1 = bb.instructions[3]  # mload 0
    load2 = bb.instructions[4]  # mload 32

    # Check definitions
    def1 = mem_ssa.get_memory_def(store1)
    def2 = mem_ssa.get_memory_def(store2)
    call_def = mem_ssa.get_memory_def(call_inst)
    call_use = mem_ssa.get_memory_use(call_inst)
    assert def1 is not None
    assert def2 is not None
    assert call_def is not None
    assert call_use is not None

    # Verify call instruction has both read and write memory areas
    assert call_def.loc.offset == 32  # Write area
    assert call_def.loc.size is None  # Write size
    assert call_use.loc.offset == 0  # Read area
    assert call_use.loc.size == 32  # Read size

    use1 = mem_ssa.get_memory_use(load1)
    use2 = mem_ssa.get_memory_use(load2)
    assert use1.reaching_def == call_def
    assert use2.reaching_def == call_def


def test_read_write_memory_clobbering_partial():
    pre = """
    function _global {
        entry:
            mstore 0, 42        # Store value at 0
            mstore 32, 100         # Store value at 32
            %ret = call 0, 0x1234, 0, 31, 2, 0, 32
            %loaded = mload 0       # Load from 0
            %loaded2 = mload 32     # Load from 32
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    # Get the block and instructions
    bb = fn.get_basic_block("entry")
    store1 = bb.instructions[0]  # mstore 0, %value
    store2 = bb.instructions[1]  # mstore 32, 100
    call_inst = bb.instructions[2]  # call instruction
    load1 = bb.instructions[3]  # mload 0
    load2 = bb.instructions[4]  # mload 32

    # Check definitions
    def1 = mem_ssa.get_memory_def(store1)
    def2 = mem_ssa.get_memory_def(store2)
    call_def = mem_ssa.get_memory_def(call_inst)
    call_use = mem_ssa.get_memory_use(call_inst)
    assert def1 is not None
    assert def2 is not None
    assert call_def is not None
    assert call_use is not None

    # Verify call instruction has both read and write memory areas
    # Write area
    assert call_def.loc.offset == 0
    assert call_def.loc.size is None
    # Read area
    assert call_use.loc.offset == 31
    assert call_use.loc.size == 2

    use1 = mem_ssa.get_memory_use(load1)
    use2 = mem_ssa.get_memory_use(load2)
    assert use1.reaching_def == call_def
    assert use2.reaching_def == call_def


def test_mark_volatile():
    pre = """
    function _global {
        _global:
            %1 = source
            mstore 0, %1
            %2 = mload 0
            stop
    }
    """

    mem_ssa, fn, _ = create_mem_ssa(pre)

    bb = fn.get_basic_block("_global")
    store = bb.instructions[1]  # mstore 0, %1
    load = bb.instructions[2]  # %2 = mload 0

    store_loc = mem_ssa.get_memory_def(store).loc
    load_loc = mem_ssa.get_memory_use(load).loc

    # Mark locations as volatile
    volatile_store_loc = mem_ssa.memalias.mark_volatile(store_loc)
    volatile_load_loc = mem_ssa.memalias.mark_volatile(load_loc)

    assert volatile_store_loc.offset == store_loc.offset
    assert volatile_store_loc.size == store_loc.size
    assert volatile_load_loc.offset == load_loc.offset
    assert volatile_load_loc.size == load_loc.size
    assert volatile_store_loc.is_volatile
    assert volatile_load_loc.is_volatile
    assert mem_ssa.memalias.may_alias(volatile_store_loc, store_loc)
    assert mem_ssa.memalias.may_alias(volatile_load_loc, load_loc)
    assert mem_ssa.memalias.may_alias(volatile_store_loc, volatile_load_loc)


def test_analyze_instruction_with_no_memory_ops():
    pre = """
    function _global {
        _global:
            %1 = 42  # Simple assignment with no memory operations
            stop
    }
    """

    mem_ssa, _, _ = create_mem_ssa(pre)

    # more check for this scenarion in tests for BasePtrAnalysis

    assert mem_ssa.memalias.alias_sets is not None


def test_phi_node_reaching_def():
    pre = """
    function _global {
        entry:
            %cond = 1
            jnz %cond, @block1, @block2
        block1:
            mstore 0, 42
            jmp @merge
        block2:
            mstore 0, 24
            jmp @merge
        merge:
            mstore 0, 84
            stop
    }
    """

    mem_ssa, fn, _ = create_mem_ssa(pre)

    block1 = fn.get_basic_block("block1")
    block2 = fn.get_basic_block("block2")
    merge_block = fn.get_basic_block("merge")

    def1 = mem_ssa.get_memory_def(block1.instructions[0])  # mstore 0, 42
    def2 = mem_ssa.get_memory_def(block2.instructions[0])  # mstore 0, 24
    def3 = mem_ssa.get_memory_def(merge_block.instructions[0])  # mstore 0, 84

    assert merge_block in mem_ssa.memory_phis, "Merge block should have a phi node"
    phi = mem_ssa.memory_phis[merge_block]

    assert len(phi.operands) == 2, "Phi node should have 2 operands"
    assert phi.operands[0][0] == def1, "First operand should be def1"
    assert phi.operands[1][0] == def2, "Second operand should be def2"
    assert phi.operands[0][1] == block1, "First operand should be from block1"
    assert phi.operands[1][1] == block2, "Second operand should be from block2"

    assert def3.reaching_def == phi, "def3's reaching definition should be live_on_entry"

    # Create a new memory definition with the same location as def3
    new_def = MemoryDef(mem_ssa.next_id, merge_block.instructions[0], MEMORY)
    mem_ssa.next_id += 1
    new_def.loc = def3.loc

    # Manually test the _get_reaching_def method
    reaching_def = mem_ssa._get_reaching_def(new_def)
    assert reaching_def == phi, "The reaching definition should be the phi node"


def test_memory_access_properties():
    live_access = MemoryAccess(0)
    assert live_access.is_live_on_entry
    assert not live_access.is_volatile
    assert live_access.id_str == "live_on_entry"

    regular_access = MemoryAccess(1)
    assert not regular_access.is_live_on_entry
    assert regular_access.id_str == "1"

    another_access = MemoryAccess(1)
    assert regular_access == another_access
    assert hash(regular_access) == hash(another_access)
    assert regular_access != live_access
    assert regular_access != "not_a_memory_access"


def test_mark_location_volatile():
    pre = """
    function _global {
        entry:
            mstore 0, 42
            mstore 32, 24
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    bb = fn.get_basic_block("entry")
    def1 = mem_ssa.get_memory_def(bb.instructions[0])  # mstore 0, 42
    def2 = mem_ssa.get_memory_def(bb.instructions[1])  # mstore 32, 24

    # Mark first location as volatile
    volatile_loc = mem_ssa.mark_location_volatile(def1.loc)
    assert volatile_loc.is_volatile
    assert def1.loc.is_volatile
    assert not def2.loc.is_volatile


def test_remove_redundant_phis():
    pre = """
    function _global {
        entry:
            %cond = 1
            jnz %cond, @block1, @block2
        block1:
            mstore 0, 42
            jmp @merge
        block2:
            mstore 0, 42  # Same value as block1
            jmp @merge
        merge:
            %val = mload 0
            jnz %val, @exit1, @exit2
        exit1:
            stop
        exit2:
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    merge_block = fn.get_basic_block("merge")

    assert merge_block in mem_ssa.memory_phis
    phi = mem_ssa.memory_phis[merge_block]

    phi.operands = [phi.operands[0], phi.operands[0]]

    # Remove redundant phis
    mem_ssa._remove_redundant_phis()
    assert merge_block not in mem_ssa.memory_phis


def test_print_context():
    pre = """
    function _global {
        entry:
            mstore 0, 42
            %val2 = mload 0
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    # "Test" print context manager to help with coverage failures :(
    with mem_ssa.print_context():
        bb = fn.get_basic_block("entry")
        store_inst = bb.instructions[0]  # mstore instruction
        load_inst = bb.instructions[1]  # mload instruction

        post_store = mem_ssa._post_instruction(store_inst)
        assert "def:" in post_store

        post_load = mem_ssa._post_instruction(load_inst)
        assert "use:" in post_load

        pre_block = mem_ssa._pre_block(bb)
        assert pre_block == ""  # No phi nodes in entry block


def test_storage_ssa():
    pre = """
    function _global {
        entry:
            sstore 0, 42
            %val2 = sload 0
            stop
    }
    """
    mem_ssa, fn, _ = create_storage_ssa(pre)

    bb = fn.get_basic_block("entry")
    store_inst = bb.instructions[0]  # sstore instruction
    load_inst = bb.instructions[1]  # sload instruction

    # Verify that the instructions have storage effects
    assert store_inst.opcode == "sstore"
    assert load_inst.opcode == "sload"
    assert Effects.STORAGE in store_inst.get_write_effects()
    assert Effects.STORAGE in load_inst.get_read_effects()

    store_def = mem_ssa.get_memory_def(store_inst)
    load_use = mem_ssa.get_memory_use(load_inst)

    assert store_def is not None
    assert load_use is not None
    assert load_use.reaching_def == store_def


def test_memory_access_str():
    pre = """
    function _global {
        entry:
            mstore 0, 42
            stop
    }
    """

    mem_ssa, fn, _ = create_mem_ssa(pre)

    entry_block = fn.get_basic_block("entry")
    store = entry_block.instructions[0]  # mstore 0, 42
    mem_def = mem_ssa.get_memory_def(store)
    assert str(mem_def) == f"MemoryDef({mem_def.id_str})"


def test_get_in_def_with_no_predecessors():
    pre = """
    function _global {
        entry:
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    block = IRBasicBlock(IRLabel("_global"), fn)
    result = mem_ssa.get_exit_def(block)
    assert result == mem_ssa.live_on_entry


def test_get_in_def_with_merge_block():
    pre = """
    function _global {
        entry:
            %cond = 1
            jnz %cond, @block1, @block2
        block1:
            jmp @merge
        block2:
            jmp @merge
        merge:
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    merge_block = fn.get_basic_block("merge")
    result = mem_ssa.get_exit_def(merge_block)
    assert result == mem_ssa.live_on_entry


def test_get_reaching_def_with_phi():
    pre = """
    function _global {
        entry:
            %cond = 1
            jnz %cond, @block1, @block2
        block1:
            mstore 0, 42
            jmp @merge
        block2:
            mstore 0, 24
            jmp @merge
        merge:
            mstore 0, 84
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    merge_block = fn.get_basic_block("merge")
    phi = mem_ssa.memory_phis[merge_block]

    # Create a new memory definition with the same location as the phi
    new_def = MemoryDef(mem_ssa.next_id, merge_block.instructions[0], MEMORY)
    mem_ssa.next_id += 1
    new_def.loc = MemoryLocation(offset=0, size=32)  # Same location as the phi

    result = mem_ssa._get_reaching_def(new_def)
    assert result == phi


def test_get_reaching_def_with_no_phi():
    pre = """
    function _global {
        entry:
            mstore 0, 42
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    entry_block = fn.get_basic_block("entry")

    new_def = MemoryDef(mem_ssa.next_id, entry_block.instructions[0], MEMORY)
    mem_ssa.next_id += 1
    new_def.loc = MemoryLocation(offset=0, size=32)

    result = mem_ssa._get_reaching_def(new_def)
    assert result == mem_ssa.live_on_entry


def test_get_clobbered_memory_access_with_phi():
    pre = """
    function _global {
        entry:
            %cond = 1
            jnz %cond, @block1, @block2
        block1:
            mstore 0, 42
            jmp @merge
        block2:
            mstore 0, 24
            jmp @merge
        merge:
            %val = mload 0
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    merge_block = fn.get_basic_block("merge")
    phi = mem_ssa.memory_phis[merge_block]

    assert mem_ssa.get_clobbered_memory_access(phi) == mem_ssa.live_on_entry


def test_get_clobbered_memory_access_ubiquitously_clobbers():
    pre = """
    function _global {
        entry:
            %1 = calldataload 0
            mstore 32, 1 ; <- this gets clobbered
            jnz %1, @block1, @block2
        block1:
            mstore 32, 42 ; <- this is the clobbered
            jmp @merge
        block2:
            mstore 0, 24
            jmp @merge
        merge: ; <- this is the merge block where the phi is
            %cond = 1
            jmp @cond
        cond:
            xor %cond, 5
            jnz %cond, @exit, @body
        body:
            mstore 0, 42
            %cond = add %cond, 1
            jmp @cond
        exit:
            %val = mload 32 ; <- this is the memory access we are testing
            sink %val
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    merge_block = fn.get_basic_block("merge")
    phi = mem_ssa.memory_phis[merge_block]

    exit_block = fn.get_basic_block("exit")
    mem_use = mem_ssa.get_memory_use(exit_block.instructions[0])

    assert mem_ssa.get_clobbered_memory_access(mem_use) == phi


def test_get_clobbered_memory_access_ubiquitously_clobbers2():
    pre = """
    function _global {
        entry:
            %1 = calldataload 0
            mstore 32, 1 ; <- this gets clobbered
            jnz %1, @block1, @block2
        block1:
            mstore 32, 42 ; <- this is the clobbered
            jmp @merge
        block2:
            mstore 32, 24  ; <- this is the clobbered
            jmp @merge
        merge: ; <- this is the merge block where the phi is
            %cond = 1
            jmp @cond
        cond:
            xor %cond, 5
            jnz %cond, @exit, @body
        body:
            mstore 0, 42
            %cond = add %cond, 1
            jmp @cond
        exit:
            %val = mload 32 ; <- this is the memory access we are testing
            sink %val
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    merge_block = fn.get_basic_block("merge")
    phi = mem_ssa.memory_phis[merge_block]

    exit_block = fn.get_basic_block("exit")
    mem_use = mem_ssa.get_memory_use(exit_block.instructions[0])

    assert mem_ssa.get_clobbered_memory_access(mem_use) == phi


def test_get_clobbered_memory_access_with_live_on_entry(dummy_mem_ssa):
    mem_ssa, _, _ = dummy_mem_ssa

    result = mem_ssa.get_clobbered_memory_access(mem_ssa.live_on_entry)
    assert result is None


def test_post_instruction_with_no_memory_ops():
    pre = """
    function _global {
        entry:
            %val = 42
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    entry_block = fn.get_basic_block("entry")
    inst = entry_block.instructions[0]

    result = mem_ssa._post_instruction(inst)
    assert result == ""


def test_post_instruction_with_memory_use():
    pre = """
    function _global {
        entry:
            %val = mload 0
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    entry_block = fn.get_basic_block("entry")
    inst = entry_block.instructions[0]

    result = mem_ssa._post_instruction(inst)
    assert "use:" in result


def test_post_instruction_with_memory_def():
    pre = """
    function _global {
        entry:
            mstore 0, 42
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    entry_block = fn.get_basic_block("entry")
    inst = entry_block.instructions[0]

    result = mem_ssa._post_instruction(inst)
    assert "def:" in result


def test_pre_block_with_phi():
    pre = """
    function _global {
        entry:
            %cond = 1
            jnz %cond, @block1, @block2
        block1:
            mstore 0, 42
            jmp @merge
        block2:
            mstore 0, 24
            jmp @merge
        merge:
            mstore 0, 84
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    merge_block = fn.get_basic_block("merge")

    result = mem_ssa._pre_block(merge_block)
    assert "phi:" in result


def test_pre_block_without_phi():
    pre = """
    function _global {
        entry:
            mstore 0, 42
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    entry_block = fn.get_basic_block("entry")

    result = mem_ssa._pre_block(entry_block)
    assert result == ""


def test_large_write_small_read_clobber():
    """
    Test that a large write (e.g., calldatacopy of 64 bytes) correctly clobbers
    a smaller read (e.g., mload of 32 bytes) when the read is fully contained
    within the write region.

    This tests the fix for the reversed containment check in _walk_for_clobbered_access.
    The check should be: current.loc.completely_contains(query_loc)
    NOT: query_loc.completely_contains(current.loc)
    """
    pre = """
    function _global {
        entry:
            calldatacopy 0, 0, 64
            %1 = mload 16
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    entry_block = fn.get_basic_block("entry")
    calldatacopy_inst = entry_block.instructions[0]
    mload_inst = entry_block.instructions[1]

    # Verify the memory locations
    calldatacopy_def = mem_ssa.get_memory_def(calldatacopy_inst)
    mload_use = mem_ssa.get_memory_use(mload_inst)

    assert calldatacopy_def is not None
    assert mload_use is not None

    # calldatacopy writes [0, 64), mload reads [16, 48)
    assert calldatacopy_def.loc.offset == 0
    assert calldatacopy_def.loc.size == 64
    assert mload_use.loc.offset == 16
    assert mload_use.loc.size == 32

    # Verify the containment relationship
    assert calldatacopy_def.loc.completely_contains(
        mload_use.loc
    ), "calldatacopy [0,64) should completely contain mload [16,48)"
    assert not mload_use.loc.completely_contains(
        calldatacopy_def.loc
    ), "mload [16,48) should NOT completely contain calldatacopy [0,64)"

    # The clobber should be the calldatacopy, NOT live_on_entry
    clobber = mem_ssa.get_clobbered_memory_access(mload_use)
    assert clobber is not None, "Should find a clobber"
    assert not clobber.is_live_on_entry, (
        "Clobber should be calldatacopy, not live_on_entry. "
        "This indicates the containment check in _walk_for_clobbered_access is reversed."
    )
    assert isinstance(clobber, MemoryDef)
    assert clobber.store_inst == calldatacopy_inst


def test_small_write_large_read_no_clobber():
    """
    Test that a small write does NOT clobber a larger read that extends beyond it.
    This is the correct behavior - partial coverage is not a complete clobber.
    """
    pre = """
    function _global {
        entry:
            mstore 16, 42
            mcopy 0, 0, 64
            stop
    }
    """
    mem_ssa, fn, _ = create_mem_ssa(pre)

    entry_block = fn.get_basic_block("entry")
    mstore_inst = entry_block.instructions[0]
    mcopy_inst = entry_block.instructions[1]

    mstore_def = mem_ssa.get_memory_def(mstore_inst)
    mcopy_use = mem_ssa.get_memory_use(mcopy_inst)

    assert mstore_def is not None
    assert mcopy_use is not None

    # mstore writes [16, 48), mcopy reads [0, 64)
    assert mstore_def.loc.offset == 16
    assert mstore_def.loc.size == 32
    assert mcopy_use.loc.offset == 0
    assert mcopy_use.loc.size == 64

    # The mstore does NOT completely contain the mcopy read
    assert not mstore_def.loc.completely_contains(
        mcopy_use.loc
    ), "mstore [16,48) should NOT completely contain mcopy read [0,64)"

    # Therefore, clobber should be live_on_entry (no complete clobber found)
    clobber = mem_ssa.get_clobbered_memory_access(mcopy_use)
    assert clobber is not None
    assert (
        clobber.is_live_on_entry
    ), "No complete clobber should be found - mstore only partially covers the read"
