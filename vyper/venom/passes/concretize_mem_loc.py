from collections import defaultdict
from typing import Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis
from vyper.venom.basicblock import (
    IRAbstractMemLoc,
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
from vyper.exceptions import CompilerPanic


class ConcretizeMemLocPass(IRPass):
    allocated_in_bb: dict[IRBasicBlock, int]

    def run_pass(self):
        self.allocator = self.function.ctx.mem_allocator
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self.allocator.start_fn_allocation()

        self.mem_liveness = MemLiveness(self.function, self.cfg, self.dfg, self.allocator)
        self.mem_liveness.analyze()

        livesets = list(self.mem_liveness.livesets.items())
        already_allocated = [item for item in livesets if item[0]._id in self.allocator.allocated]
        to_allocate = [item for item in livesets if item[0]._id not in self.allocator.allocated]
        # (note this is *heuristic*; our goal is to minimize conflicts
        # between livesets)
        to_allocate.sort(key=lambda x: len(x[1]), reverse=False)

        self.allocator.already_allocated([mem for mem, _ in already_allocated])

        max_curr = 0
        # REVIEW: for ix, (mem, live_insts) in enumerate(livesets):
        # REVIEW: note, this is O(n^2)
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
            max_curr = max(self.allocator.curr, max_curr)

        self.allocator.curr = max_curr

        for bb in self.function.get_basic_blocks():
            self._handle_bb(bb)

        self.allocator.end_fn_allocation(fn=self.function)

        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _handle_bb(self, bb: IRBasicBlock):
        for inst in bb.instructions:
            new_ops = [self._handle_op(op, inst) for op in inst.operands]
            inst.operands = new_ops
            if inst.opcode == "gep":
                inst.opcode = "add"
            elif inst.opcode == "mem_deploy_start":
                inst.opcode = "assign"

    def _handle_op(self, op: IROperand, inst: IRInstruction) -> IROperand:
        if isinstance(op, IRAbstractMemLoc) and op._id in self.allocator.allocated:
            return IRLiteral(self.allocator.allocated[op._id][0] + op.offset)
        elif isinstance(op, IRAbstractMemLoc):
            # the invariant that all should be already allocated
            # only holds if all the dead stores are eliminated
            # but that does not seems like is a case so far
            # so this is allocating the memory after all other mem
            # if this case occurs
            return IRLiteral(self.allocator.allocate(op) + op.offset)
        else:
            return op


# with there opcodes we do not have whole knowledge of memory location usage
_CALL_OPCODES = frozenset(["invoke", "staticcall", "call", "delegatecall"])


class MemLiveness:
    function: IRFunction
    cfg: CFGAnalysis
    mem_allocator: MemoryAllocator

    liveat: dict[IRInstruction, OrderedSet[IRAbstractMemLoc]]
    livesets: dict[IRAbstractMemLoc, OrderedSet[IRInstruction]]

    used: dict[IRInstruction, OrderedSet[IRAbstractMemLoc]]

    def __init__(
        self,
        function: IRFunction,
        cfg: CFGAnalysis,
        dfg: DFGAnalysis,
        mem_allocator: MemoryAllocator,
    ):
        self.function = function
        self.cfg = cfg
        self.dfg = dfg
        self.used = defaultdict(OrderedSet)
        self.liveat = defaultdict(OrderedSet)
        self.mem_allocator = mem_allocator

    def analyze(self):
        upper_bound = self.function.num_basic_blocks ** 2 + 1
        for _ in range(upper_bound):
            change = False
            for bb in self.cfg.dfs_post_walk:
                # REVIEW: these don't need to be in the same loop, right?
                # (if so please add note)
                # REVIEW: note "natural" order for handle_bb (maybe should be
                # renamed to compute_liveat) is post walk,
                # natural order for handle_used is pre walk.
                # REVIEW: kind of prefer a worklist, it's more "standard"
                # / in line with the rest of the codebase
                change |= self._handle_liveat(bb)
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
        curr: OrderedSet[IRAbstractMemLoc] = OrderedSet()
        if len(succs := self.cfg.cfg_out(bb)) > 0:
            for other in (self.liveat[succ.instructions[0]] for succ in succs):
                curr.update(other)

        before = self.liveat[bb.instructions[0]]

        for inst in reversed(bb.instructions):
            write_op = get_memory_write_op(inst)
            write_ops = self._find_base_ptrs(write_op)
            read_op = get_memory_read_op(inst)
            read_ops = self._find_base_ptrs(read_op)

            for read_op in read_ops:
                assert isinstance(read_op, IRAbstractMemLoc)
                curr.add(read_op.no_offset())

            if inst.opcode == "invoke":
                label = inst.operands[0]
                assert isinstance(label, IRLabel)
                fn = self.function.ctx.get_function(label)
                # this lets us deallocate internal 
                # function memory after it's dead
                curr.addmany(self.mem_allocator.mems_used[fn])

            if inst.opcode in _CALL_OPCODES:
                for op in inst.operands:
                    if not isinstance(op, IRAbstractMemLoc):
                        continue
                    # this case is for the memory places that are
                    # inlucluded as parameter as in stack parameters
                    curr.add(op.no_offset())

            self.liveat[inst] = curr.copy()

            for write_op in write_ops:
                assert isinstance(write_op, IRAbstractMemLoc)
                size = get_write_size(inst)
                assert size is not None
                if not isinstance(size, IRLiteral):
                    # if it is literal then
                    # we do not handle it
                    continue
                if write_op in curr and size.value == write_op.size:
                    # if the memory is overriden completelly
                    # you dont have to consider the memory location
                    # before this point live since the value that
                    # is currently in there will be overriden
                    # either way
                    curr.remove(write_op.no_offset())
                if write_op._id in (op._id for op in read_ops):
                    # this is the case for instruction
                    # with more then one mem location
                    # and there could be the case that
                    # both of them would be same abstract
                    # memloc you cannot remove it 
                    # so this is just to not allow it
                    curr.add(write_op.no_offset())

        if before != self.liveat[bb.instructions[0]]:
            return True

        return False

    def _handle_used(self, bb: IRBasicBlock) -> bool:
        # this is to get positions where the memory location
        # are used/already used so we dont allocate
        # memory before the place where it is firstly used
        curr: OrderedSet[IRAbstractMemLoc] = OrderedSet(self.function.allocated_args.values())
        if len(preds := self.cfg.cfg_in(bb)) > 0:
            for other in (self.used[pred.instructions[-1]] for pred in preds):
                curr.update(other)

        before = self.used[bb.instructions[-1]]
        for inst in bb.instructions:
            for op in inst.operands:
                if not isinstance(op, IRAbstractMemLoc):
                    continue
                curr.add(op.no_offset())
            if inst.opcode == "invoke":
                label = inst.operands[0]
                assert isinstance(label, IRLabel)
                fn = self.function.ctx.get_function(label)
                curr.addmany(self.mem_allocator.mems_used[fn])
            self.used[inst] = curr.copy()
        return before != curr

    def _find_base_ptrs(self, op: Optional[IROperand]) -> set[IRAbstractMemLoc]:
        if op is None:
            return set()
        if isinstance(op, IRAbstractMemLoc):
            return {op}
        if not isinstance(op, IRVariable):
            return set()

        inst = self.dfg.get_producing_instruction(op)
        assert inst is not None
        if inst.opcode == "gep":
            mem = inst.operands[0]
            return self._find_base_ptrs(mem)
        elif inst.opcode == "assign":
            mem = inst.operands[0]
            return self._find_base_ptrs(mem)
        elif inst.opcode == "phi":
            res = set()
            for _, var in inst.phi_operands:
                src = self._find_base_ptrs(var)
                res.update(src)
            return res
        return set()
