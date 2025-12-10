from collections import defaultdict
from typing import Optional

from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, BasePtrAnalysis
from vyper.venom.analysis.base_ptr_analysis import BasePtr
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.function import IRFunction
from vyper.venom.memory_allocator import MemoryAllocator
from vyper.venom.memory_location import get_memory_read_op, get_memory_write_op, get_write_size
from vyper.venom.passes.base_pass import IRPass


class ConcretizeMemLocPass(IRPass):
    allocated_in_bb: dict[IRBasicBlock, int]

    def run_pass(self):
        self.allocator = self.function.ctx.mem_allocator
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)

        self.mem_liveness = MemLiveness(
                self.function,
                self.cfg,
                self.dfg,
                self.base_ptrs,
                self.allocator,
        )
        self.mem_liveness.analyze()

        self.allocator.start_fn_allocation(self.function)

        livesets = list(self.mem_liveness.livesets.items())
        already_allocated = [item for item in livesets if self.allocator.is_allocated(item[0])]
        to_allocate = [item for item in livesets if not self.allocator.is_allocated(item[0])]
        # (note this is *heuristic*; our goal is to minimize conflicts
        # between livesets)
        to_allocate.sort(key=lambda x: len(x[1]), reverse=False)
        print(livesets)
        print(self.function)

        self.allocator.add_allocated([mem for mem, _ in already_allocated])

        max_eom = 0
        for mem, insts in to_allocate:
            self.allocator.reset()

            for before_mem, before_insts in already_allocated:
                if len(OrderedSet.intersection(insts, before_insts)) == 0:
                    continue
                self.allocator.reserve(BasePtr.from_alloca(before_mem))
            self.allocator.allocate(mem)
            already_allocated.append((mem, insts))
            # this is necessary because of the case that is described
            # in the _handle_op method
            max_eom = max(self.allocator.eom, max_eom)

        # set allocator eom to end of currently allocated memory in function,
        # so that allocate() in handle_op is able to allocate from proper
        # starting place
        self.allocator.eom = max_eom
        self.allocator.reserve_all()

        for bb in self.function.get_basic_blocks():
            self._handle_bb(bb)

        self.allocator.end_fn_allocation()

        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _handle_bb(self, bb: IRBasicBlock):
        for inst in bb.instructions:
            new_ops = [self._handle_op(op) for op in inst.operands]
            inst.operands = new_ops
            if inst.opcode == "gep":
                inst.opcode = "add"
            elif inst.opcode == "mem_deploy_start":
                inst.opcode = "assign"

    def _handle_op(self, op: IROperand) -> IROperand:
        """
        rewrite IRAbstractMemLocs to IRLiterals
        """
        base_ptr = self.base_ptrs.base_ptr_from_op(op)
        if base_ptr is None:
            return op
        if base_ptr.offset is None:
            return op

        # common case, allocator already allocated
        if self.allocator.is_allocated(base_ptr):
            return self.allocator.get_concrete(base_ptr)

        else:
            # unallocated alloca, we need to allocate it.
            #
            # the invariant that all abstract mem locs should be already
            # allocated by this stage (due to how livesets are calculated)
            # only holds if all the dead stores are eliminated.
            # however, this doesn't always seem to be the case, so we allocate
            # these memory locations now.
            self.allocator.allocate(base_ptr)
            return self.allocator.get_concrete(base_ptr)


class MemLiveness:
    function: IRFunction
    cfg: CFGAnalysis
    mem_allocator: MemoryAllocator

    # alloca/palloca which value is live at postion
    liveat: dict[IRInstruction, OrderedSet[IRInstruction]]
    # where is each alloca/palloca live
    livesets: dict[IRInstruction, OrderedSet[IRInstruction]]

    used: dict[IRInstruction, OrderedSet[IRInstruction]]

    def __init__(
        self,
        function: IRFunction,
        cfg: CFGAnalysis,
        dfg: DFGAnalysis,
        base_ptrs: BasePtrAnalysis,
        mem_allocator: MemoryAllocator,
    ):
        self.function = function
        self.cfg = cfg
        self.dfg = dfg
        self.base_ptrs = base_ptrs
        self.used = defaultdict(OrderedSet)
        self.liveat = defaultdict(OrderedSet)
        self.mem_allocator = mem_allocator

    def analyze(self):
        upper_bound = self.function.num_basic_blocks**2 + 1
        for _ in range(upper_bound):
            change = False
            # these parts of analysis are better (performance)
            # in different orders so it is split into
            # different loops
            for bb in self.cfg.dfs_post_walk:
                change |= self._handle_liveat(bb)
            for bb in self.cfg.dfs_pre_walk:
                change |= self._handle_used(bb)

            if not change:
                break
        else:
            raise CompilerPanic("Uppper bound in memory liveness reached")

        self.livesets = defaultdict(OrderedSet)
        for inst, mems in self.liveat.items():
            for mem in mems:
                if mem in self.used[inst]:
                    self.livesets[mem].add(inst)

    def _handle_liveat(self, bb: IRBasicBlock) -> bool:
        live: OrderedSet[IRInstruction] = OrderedSet()
        if len(succs := self.cfg.cfg_out(bb)) > 0:
            for other in (self.liveat[succ.instructions[0]] for succ in succs):
                live.update(other)

        before = self.liveat[bb.instructions[0]]

        for inst in reversed(bb.instructions):
            write_op = get_memory_write_op(inst)
            write_ops = self._find_base_ptrs(write_op)
            read_op = get_memory_read_op(inst)
            read_ops = self._find_base_ptrs(read_op)

            for read_op in read_ops:
                live.add(read_op.source)

            if inst.opcode == "invoke":
                label = inst.operands[0]
                assert isinstance(label, IRLabel)
                fn = self.function.ctx.get_function(label)
                # this lets us deallocate internal
                # function memory after it's dead
                live.addmany(self.mem_allocator.mems_used[fn])

                for op in inst.operands:
                    ptr = self.base_ptrs.base_ptr_from_op(op)
                    if ptr is not None:
                        # this case is for any buffers which are
                        # passed to invoke as a stack parameter.
                        live.add(ptr.source)

            self.liveat[inst] = live.copy()

            for write_op in write_ops:
                size = get_write_size(inst)
                assert size is not None
                if not isinstance(size, IRLiteral):
                    # if the size is not a literal then we do not handle it
                    continue
                if write_op in live and size.value == write_op.size:
                    # if the memory segment is overriden completely
                    # we dont have to consider the memory location
                    # before this point live, since any values that
                    # are currently in there will be overriden either way
                    live.remove(write_op.source)
                if write_op.source in (op.source for op in read_ops):
                    # the instruction reads and writes from the same memory
                    # location, we cannot remove it from the liveset
                    live.add(write_op.source)

        if before != self.liveat[bb.instructions[0]]:
            return True

        return False

    def _handle_used(self, bb: IRBasicBlock) -> bool:
        # this is to get positions where the memory location
        # are used/already used so we dont allocate
        # memory before the place where it is firstly used
        curr: OrderedSet[IRInstruction] = OrderedSet(self.function.allocated_args.values())
        if len(preds := self.cfg.cfg_in(bb)) > 0:
            for other in (self.used[pred.instructions[-1]] for pred in preds):
                curr.update(other)

        before = self.used[bb.instructions[-1]]
        for inst in bb.instructions:
            for op in inst.operands:
                ptr = self.base_ptrs.base_ptr_from_op(op)
                if ptr is None:
                    continue
                curr.add(ptr.source)
            if inst.opcode == "invoke":
                label = inst.operands[0]
                assert isinstance(label, IRLabel)
                fn = self.function.ctx.get_function(label)
                curr.addmany(self.mem_allocator.mems_used[fn])
            self.used[inst] = curr.copy()
        return before != curr

    def _find_base_ptrs(self, op: Optional[IROperand]) -> set[BasePtr]:
        if op is None:
            return set()
        if not isinstance(op, IRVariable):
            return set()
        return self.base_ptrs.get_all_posible_memory(op)
