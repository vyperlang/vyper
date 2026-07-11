from vyper.venom.basicblock import IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import MemoryLocation, memory_read_ops


def test_completely_overlaps():
    # Create memory locations with different offsets and sizes
    loc1 = MemoryLocation(offset=0, size=32)
    loc2 = MemoryLocation(offset=0, size=32)  # Same as loc1
    loc3 = MemoryLocation(offset=0, size=64)  # Larger than loc1
    loc4 = MemoryLocation(offset=16, size=16)  # Inside loc1
    loc5 = MemoryLocation(offset=16, size=32)  # Partially overlaps loc1
    loc6 = MemoryLocation(offset=32, size=32)  # Adjacent to loc1

    assert loc1.completely_contains(loc1)
    assert loc1.completely_contains(loc2)
    assert loc3.completely_contains(loc1)
    assert not loc1.completely_contains(loc3)
    assert loc1.completely_contains(loc4)
    assert not loc4.completely_contains(loc1)
    assert not loc1.completely_contains(loc5)
    assert not loc5.completely_contains(loc1)
    assert not loc1.completely_contains(loc6)

    # Test with EMPTY and FULL memory access
    full_loc = MemoryLocation(offset=0, size=None)
    assert not MemoryLocation.EMPTY.completely_contains(loc1)
    assert loc1.completely_contains(MemoryLocation.EMPTY)
    assert not full_loc.completely_contains(loc1)
    assert not loc1.completely_contains(full_loc)


def test_memory_read_max_size_metadata_survives_copy():
    size = IRVariable("%size")
    inst = IRInstruction("mcopy", [size, IRVariable("%src"), IRVariable("%dst")])
    inst.parent = IRFunction(IRLabel("main")).entry
    inst.memory_read_max_size = 64

    assert memory_read_ops(inst).size == size
    assert memory_read_ops(inst).max_size == IRLiteral(64)
    assert inst.copy().memory_read_max_size == 64
