from vyper.venom.basicblock import IRAbstractMemLoc
from vyper.venom.memory_location import (
    MemoryLocation,
    MemoryLocationAbstract,
    MemoryLocationSegment,
)


def test_abstract_may_overlap():
    loc1 = MemoryLocationAbstract(abstract_mem_id=0, maximum_size=256, segment=MemoryLocationSegment(offset=0, size=32))
    loc2 = MemoryLocationAbstract(abstract_mem_id=0, maximum_size=256, segment=MemoryLocationSegment(offset=128, size=32))

    assert not MemoryLocation.may_overlap(loc1, loc2)
