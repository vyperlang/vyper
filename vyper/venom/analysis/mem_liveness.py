from collections import defaultdict
from typing import Optional

from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.memory_location import (
    Allocation,
    get_memory_read_op,
    get_memory_write_op,
    get_write_size,
)

from .analysis import IRAnalysis
from .base_ptr_analysis import BasePtrAnalysis, Ptr
from .cfg import CFGAnalysis


class MemLivenessAnalysis(IRAnalysis):
    """
    Compute allocation liveness ranges used by memory concretization.
    """

    liveat: dict[IRInstruction, OrderedSet[Allocation]]
    used: dict[IRInstruction, OrderedSet[Allocation]]
    livesets: dict[Allocation, OrderedSet[IRInstruction]]
    cfg: CFGAnalysis

    def analyze(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.mem_allocator = self.function.ctx.mem_allocator

        self.used = defaultdict(OrderedSet)
        self.liveat = defaultdict(OrderedSet)
        self.livesets = defaultdict(OrderedSet)

        upper_bound = self.function.num_basic_blocks**2 + 1
        for _ in range(upper_bound):
            change = False
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
                live.addmany(self.mem_allocator.mems_used[fn])

                for op in inst.operands:
                    ptrs = self._find_base_ptrs(op)
                    for ptr in ptrs:
                        live.add(ptr.base_alloca)

            self.liveat[inst] = live.copy()

            for write_ptr in write_ptrs:
                size = get_write_size(inst)
                if not isinstance(size, IRLiteral):
                    continue
                alloca = write_ptr.base_alloca
                if alloca in live and size.value == alloca.alloca_size:
                    live.remove(alloca)
                if alloca in (ptr.base_alloca for ptr in read_ptrs):
                    live.add(alloca)

        return before != self.liveat[bb.instructions[0]]

    def _handle_used(self, bb: IRBasicBlock) -> bool:
        used: OrderedSet[Allocation] = OrderedSet()
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
        if op is None or not isinstance(op, IRVariable):
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
