from vyper.venom.passes.base_pass import IRPass
from vyper.venom.basicblock import IROperand, IRAbstractMemLoc
from vyper.venom.memory_allocator import MemoryAllocator

class ConcretizeMemLocPass(IRPass):
    def run_pass(self, mem_allocator: MemoryAllocator):
        self.allocator = mem_allocator
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst == "codecopyruntime":
                    continue
                new_ops = [self._handle_op(op) for op in inst.operands]
                inst.operands = new_ops
                if inst.opcode == "gep":
                    inst.opcode = "add"
                elif inst.opcode == "mem_deploy_start":
                    inst.opcode = "assign"
                elif inst.opcode == "codecopyruntime":
                    inst.opcode = "codecopy"

    def _handle_op(self, op: IROperand) -> IROperand:
        if isinstance(op, IRAbstractMemLoc):
            return self.allocator.get_place(op).get_offset_lit()
        else:
            return op
