from vyper.venom.basicblock import IRInstruction, IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.memory_allocator import MemoryAllocator
from vyper.venom.memory_location import Allocation


def test_allocate_overlapping_reserved_intervals():
    ctx = IRContext()
    fn = ctx.create_function("main")
    bb = fn.entry

    imm_inst = IRInstruction("alloca", [IRLiteral(480), IRLiteral(1)], outputs=[IRVariable("%imm")])
    tmp_inst = IRInstruction("alloca", [IRLiteral(96), IRLiteral(2)], outputs=[IRVariable("%tmp")])
    buf_inst = IRInstruction("alloca", [IRLiteral(96), IRLiteral(3)], outputs=[IRVariable("%buf")])
    bb.insert_instruction(imm_inst)
    bb.insert_instruction(tmp_inst)
    bb.insert_instruction(buf_inst)

    imm = Allocation(imm_inst)
    tmp = Allocation(tmp_inst)
    buf = Allocation(buf_inst)

    allocator = MemoryAllocator()
    allocator.start_fn_allocation(fn)
    allocator.set_position(imm, 0)
    allocator.set_position(tmp, 160)
    allocator.reserve(imm)
    allocator.reserve(tmp)

    assert allocator.allocate(buf) == 480
