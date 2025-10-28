from vyper.venom.memory_location import MemoryLocationAbstract, MemoryLocation
from vyper.venom.basicblock import IRAbstractMemLoc

def test_abstract_may_overlap():
    op1 = IRAbstractMemLoc(256, offset=0, force_id=0)
    op2 = IRAbstractMemLoc(256, offset=128, force_id=0)
    loc1 = MemoryLocationAbstract(op1, 32)
    loc2 = MemoryLocationAbstract(op2, 32)

    assert not MemoryLocation.may_overlap(loc1, loc2)
