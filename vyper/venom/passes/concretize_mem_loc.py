from vyper.venom.basicblock import IRAbstractMemLoc, IROperand, IRLabel, IRBasicBlock
from vyper.venom.memory_allocator import MemoryAllocator
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.analysis import CFGAnalysis
from collections import defaultdict, deque


class ConcretizeMemLocPass(IRPass):
    allocated_in_bb: dict[IRBasicBlock, int]
    orig: int

    def run_pass(self, mem_allocator: MemoryAllocator):
        self.allocator = mem_allocator
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        mem_allocator.start_fn_allocation(self._get_used(mem_allocator))

        tmp = mem_allocator.curr
        self.orig = tmp
        self.allocated_in_bb = defaultdict(lambda: tmp)

        worklist = deque(bb for bb in self.function.get_basic_blocks() if len(self.cfg.cfg_out(bb)) == 0)
        visited = set()
        while len(worklist) > 0:
            bb = worklist.popleft()
            self._allocate_bb(mem_allocator, bb)
            for pred in self.cfg.cfg_in(bb):
                if pred in visited:
                    continue
                visited.add(pred)
                worklist.append(pred)

        mem_allocator.end_fn_allocation(self.function)

    def _allocate_bb(self, mem_allocator: MemoryAllocator, bb: IRBasicBlock):
        #print(bb.label)
        if len(succs := self.cfg.cfg_out(bb)) > 0:
            mem_allocator.curr = max(self.allocated_in_bb[succ] for succ in succs)
        else:
            mem_allocator.curr = self.orig

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

        self.allocated_in_bb[bb] = mem_allocator.curr
        

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
