from vyper.venom.memory_location import MemoryLocation, MemoryLocationSegment


def test_completely_overlaps():
    # Create memory locations with different offsets and sizes
    loc1 = MemoryLocationSegment(_offset=0, _size=32)
    loc2 = MemoryLocationSegment(_offset=0, _size=32)  # Same as loc1
    loc3 = MemoryLocationSegment(_offset=0, _size=64)  # Larger than loc1
    loc4 = MemoryLocationSegment(_offset=16, _size=16)  # Inside loc1
    loc5 = MemoryLocationSegment(_offset=16, _size=32)  # Partially overlaps loc1
    loc6 = MemoryLocationSegment(_offset=32, _size=32)  # Adjacent to loc1

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
    full_loc = MemoryLocationSegment(_offset=0, _size=None)
    assert not MemoryLocation.EMPTY.completely_contains(loc1)
    assert loc1.completely_contains(MemoryLocation.EMPTY)
    assert not full_loc.completely_contains(loc1)
    assert not loc1.completely_contains(full_loc)
