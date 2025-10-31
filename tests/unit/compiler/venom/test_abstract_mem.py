from vyper.venom.memory_location import MemoryLocationAbstract, MemoryLocation
from vyper.venom.basicblock import IRAbstractMemLoc

def test_abstract_may_overlap():
    op1 = IRAbstractMemLoc(256, offset=0, force_id=0)
    op2 = IRAbstractMemLoc(256, offset=128, force_id=0)
    loc1 = MemoryLocationAbstract(op=op1, _offset=op1.offset, _size=32)
    loc2 = MemoryLocationAbstract(op=op2, _offset=op2.offset, _size=32)

    assert not MemoryLocation.may_overlap(loc1, loc2)
