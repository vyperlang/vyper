from collections import defaultdict
from typing import Optional

from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis import BasePtrAnalysis, CFGAnalysis, DFGAnalysis
from vyper.venom.analysis.base_ptr_analysis import Ptr
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
from vyper.venom.memory_location import (
    Allocation,
    get_memory_read_op,
    get_memory_write_op,
    get_write_size,
)
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.machinery.inst_updater import InstUpdater


class ConcretizeMemLocPass(IRPass):
    allocated_in_bb: dict[IRBasicBlock, int]
    # FixMemLocationsPass seeds pinned allocas whose abstract locations are concretized here.
    # LowerDloadPass inserts allocas
    required_predecessors = ("FixMemLocationsPass", "LowerDloadPass")

    def run_pass(self):
        self.allocator = self.function.ctx.mem_allocator
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self.base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)

        self.mem_liveness = MemLiveness(
            self.function, self.cfg, self.dfg, self.base_ptrs, self.allocator
        )
        self.mem_liveness.analyze()

        self.allocator.start_fn_allocation(self.function)

        livesets = list(self.mem_liveness.livesets.items())
        already_allocated = [item for item in livesets if self.allocator.is_allocated(item[0])]
        to_allocate = [item for item in livesets if not self.allocator.is_allocated(item[0])]
        # (note this is *heuristic*; our goal is to minimize conflicts
        # between livesets)
        to_allocate.sort(key=lambda x: len(x[1]), reverse=False)

        self.allocator.add_allocated([mem for mem, _ in already_allocated])

        for mem, insts in to_allocate:
            self.allocator.reset()

            for before_mem, before_insts in already_allocated:
                if len(OrderedSet.intersection(insts, before_insts)) == 0:
                    continue
                self.allocator.reserve(before_mem)
            self.allocator.allocate(mem)
            already_allocated.append((mem, insts))
            # this is necessary because of the case that is described
            # in the _handle_op method

        self.allocator.reserve_all()

        for bb in self.function.get_basic_blocks():
            self._handle_bb(bb)

        self.allocator.end_fn_allocation()

        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _handle_bb(self, bb: IRBasicBlock):
        for inst in bb.instructions:
            if inst.opcode in ("alloca", "palloca", "calloca"):
                base_ptr = self.base_ptrs.ptr_from_op(inst.output)
                if base_ptr is None:
                    # calloca's palloca was nop'd (DSE removed stores, then
                    # RemoveUnusedVariables nop'd the palloca). The memory
                    # isn't used, so remove calloca and its uses.
                    assert inst.opcode == "calloca", inst
                    self._remove_unused_calloca(inst)
                    continue
                assert self.allocator.is_allocated(
                    base_ptr.base_alloca
                ), f"alloca not allocated by livesets: {inst}"
                concrete = self.allocator.get_concrete(base_ptr)
                self.updater.replace(inst, "assign", [concrete])
            if inst.opcode == "gep":
                inst.opcode = "add"

    def _remove_unused_calloca(self, inst: IRInstruction):
        to_remove = self.dfg.get_transitive_uses(inst)
        self.updater.nop_multi(to_remove)


class MemLiveness:
    function: IRFunction
    cfg: CFGAnalysis
    mem_allocator: MemoryAllocator

    # liveat - where allocations are live from for the first time
    liveat: dict[IRInstruction, OrderedSet[Allocation]]

    # used - where allocations are used
    used: dict[IRInstruction, OrderedSet[Allocation]]

    # set of instructions where allocations are live
    # (i.e. first live through last use)
    livesets: dict[Allocation, OrderedSet[IRInstruction]]

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
        self.livesets = defaultdict(OrderedSet)
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

        for inst, mems in self.liveat.items():
            for mem in mems:
                if mem in self.used[inst]:
                    self.livesets[mem].add(inst)

        self._mark_store_locations_live()

    def _handle_liveat(self, bb: IRBasicBlock) -> bool:
        live: OrderedSet[Allocation] = OrderedSet()
        if len(succs := self.cfg.cfg_out(bb)) > 0:
            for other in (self.liveat[succ.instructions[0]] for succ in succs):
                live.update(other)

        before = self.liveat[bb.instructions[0]]

        for inst in reversed(bb.instructions):
            write_op = get_memory_write_op(inst)
            write_ptrs = self._find_base_ptrs(write_op)
            read_op = get_memory_read_op(inst)
            read_ptrs = self._find_base_ptrs(read_op)

            for read_ptr in read_ptrs:
                live.add(read_ptr.base_alloca)

            if inst.opcode == "invoke":
                label = inst.operands[0]
                assert isinstance(label, IRLabel)
                fn = self.function.ctx.get_function(label)
                # this lets us deallocate internal
                # function memory after it's dead
                live.addmany(self.mem_allocator.mems_used[fn])

                for op in inst.operands:
                    # REVIEW: changed from ptr_from_op
                    ptrs = self._find_base_ptrs(op)
                    for ptr in ptrs:
                        # this case is for any buffers which are
                        # passed to invoke as a stack parameter.
                        live.add(ptr.base_alloca)

            self.liveat[inst] = live.copy()

            for write_ptr in write_ptrs:
                size = get_write_size(inst)
                if not isinstance(size, IRLiteral):
                    # if the size is not a literal then we do not handle it
                    continue
                alloca = write_ptr.base_alloca
                if alloca in live and size.value == alloca.alloca_size:
                    # if the memory segment is overriden completely
                    # we dont have to consider the memory location
                    # before this point live, since any values that
                    # are currently in there will be overriden either way
                    live.remove(alloca)
                if alloca in (ptr.base_alloca for ptr in read_ptrs):
                    # the instruction reads and writes from the same memory
                    # location, we cannot remove it from the liveset
                    live.add(alloca)

        if before != self.liveat[bb.instructions[0]]:
            return True

        return False

    def _handle_used(self, bb: IRBasicBlock) -> bool:
        # this is to get positions where the memory location
        # are used/already used so we dont allocate
        # memory before the place where it is firstly used
        used: OrderedSet[Allocation] = OrderedSet(
            Allocation(inst) for inst in self.function.get_live_pallocas()
        )
        if len(preds := self.cfg.cfg_in(bb)) > 0:
            for other in (self.used[pred.instructions[-1]] for pred in preds):
                used.update(other)

        before = self.used[bb.instructions[-1]]
        for inst in bb.instructions:
            for op in inst.operands:
                ptrs = self._find_base_ptrs(op)
                used.addmany(ptr.base_alloca for ptr in ptrs)
            if inst.opcode == "invoke":
                label = inst.operands[0]
                assert isinstance(label, IRLabel)
                fn = self.function.ctx.get_function(label)
                used.addmany(self.mem_allocator.mems_used[fn])
            self.used[inst] = used.copy()
        return before != used

    def _find_base_ptrs(self, op: Optional[IROperand]) -> set[Ptr]:
        if op is None:
            return set()
        if not isinstance(op, IRVariable):
            return set()
        return self.base_ptrs.get_possible_ptrs(op)

    def _mark_store_locations_live(self):
        # DSE may preserve stores whose liveness it can't disprove (e.g.,
        # when an invoke might alias the store target). MemLiveness uses a
        # different liveness model (liveat ∩ used) that can mark the same
        # alloca dead. If concretization trusts MemLiveness alone, it may
        # overlap the "dead" alloca with a live one, but the surviving
        # store still executes at runtime and clobbers the overlap.
        # Fix: any store present in the IR forces its target alloca live
        # at that instruction, preventing overlapping allocation.
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                write_op = get_memory_write_op(inst)
                for ptr in self._find_base_ptrs(write_op):
                    self.livesets[ptr.base_alloca].add(inst)
