from vyper.venom.basicblock import EMPTY_MEMORY_ACCESS, FULL_MEMORY_ACCESS, MemoryLocation


def test_completely_overlaps():
    # Create memory locations with different offsets and sizes
    loc1 = MemoryLocation(offset=0, size=32)
    loc2 = MemoryLocation(offset=0, size=32)  # Same as loc1
    loc3 = MemoryLocation(offset=0, size=64)  # Larger than loc1
    loc4 = MemoryLocation(offset=16, size=16)  # Inside loc1
    loc5 = MemoryLocation(offset=16, size=32)  # Partially overlaps loc1
    loc6 = MemoryLocation(offset=32, size=32)  # Adjacent to loc1

    assert loc1.completely_overlaps(loc1)
    assert loc1.completely_overlaps(loc2)
    assert loc3.completely_overlaps(loc1)
    assert not loc1.completely_overlaps(loc3)
    assert loc1.completely_overlaps(loc4)
    assert not loc4.completely_overlaps(loc1)
    assert not loc1.completely_overlaps(loc5)
    assert not loc5.completely_overlaps(loc1)
    assert not loc1.completely_overlaps(loc6)

    # Test with EMPTY and FULL memory access
    assert not EMPTY_MEMORY_ACCESS.completely_overlaps(loc1)
    assert not loc1.completely_overlaps(EMPTY_MEMORY_ACCESS)
    assert FULL_MEMORY_ACCESS.completely_overlaps(loc1)
    assert not loc1.completely_overlaps(FULL_MEMORY_ACCESS)
