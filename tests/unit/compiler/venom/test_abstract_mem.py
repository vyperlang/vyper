from vyper.venom.basicblock import IRAbstractMemLoc
from vyper.venom.memory_location import (
    MemoryLocation,
    MemoryLocationAbstract,
    MemoryLocationSegment,
)


def test_abstract_may_overlap():
    op1 = IRAbstractMemLoc(256, offset=0, force_id=0)
    op2 = IRAbstractMemLoc(256, offset=128, force_id=0)
    loc1 = MemoryLocationAbstract(op=op1, segment=MemoryLocationSegment(offset=op1.offset, size=32))
    loc2 = MemoryLocationAbstract(op=op2, segment=MemoryLocationSegment(offset=op2.offset, size=32))

    assert not MemoryLocation.may_overlap(loc1, loc2)
