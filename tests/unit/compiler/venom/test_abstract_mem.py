from vyper.venom.basicblock import IRInstruction, IRLiteral
from vyper.venom.memory_location import Allocation, MemoryLocation


def test_abstract_may_overlap():
    source = IRInstruction("alloca", [IRLiteral(256)])
    alloca = Allocation(source)
    loc1 = MemoryLocation(alloca=alloca, offset=0, size=32)
    loc2 = MemoryLocation(alloca=alloca, offset=128, size=32)

    assert not MemoryLocation.may_overlap(loc1, loc2)
