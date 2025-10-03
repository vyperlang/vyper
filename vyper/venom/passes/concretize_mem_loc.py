from vyper.venom.basicblock import IRAbstractMemLoc, IROperand, IRLabel
from vyper.venom.memory_allocator import MemoryAllocator
from vyper.venom.passes.base_pass import IRPass


class ConcretizeMemLocPass(IRPass):
    def run_pass(self, mem_allocator: MemoryAllocator):
        self.allocator = mem_allocator

        mem_allocator.start_fn_allocation(self._get_used(mem_allocator))

        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "codecopyruntime":
                    inst.opcode = "codecopy"
                    continue
                new_ops = [self._handle_op(op) for op in inst.operands]
                inst.operands = new_ops
                if inst.opcode == "gep":
                    inst.opcode = "add"
                elif inst.opcode == "mem_deploy_start":
                    inst.opcode = "assign"

        mem_allocator.end_fn_allocation(self.function)

    def _handle_op(self, op: IROperand) -> IROperand:
        if isinstance(op, IRAbstractMemLoc):
            return self.allocator.get_place(op).get_offset_lit()
        else:
            return op
    
    def _get_used(self, mem_alloc: MemoryAllocator) -> int:
        max_used = mem_alloc.curr
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "invoke":
                    continue

                callee_label = inst.operands[0]
                assert isinstance(callee_label, IRLabel)
                callee = self.function.ctx.get_function(callee_label)

                max_used = max(max_used, mem_alloc.function_mem_used[callee])        

        return max_used
