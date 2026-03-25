from vyper.utils import OrderedSet
from vyper.venom.analysis import BasePtrAnalysis, DFGAnalysis, MemLivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.machinery.inst_updater import InstUpdater


class ConcretizeMemLocPass(IRPass):
    allocated_in_bb: dict[IRBasicBlock, int]
    # FixMemLocationsPass seeds pinned allocas whose abstract locations are concretized here.
    # LowerDloadPass inserts allocas
    required_predecessors = ("FixMemLocationsPass", "LowerDloadPass")

    def run_pass(self):
        self.allocator = self.function.ctx.mem_allocator
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self.base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.mem_liveness = self.analyses_cache.request_analysis(MemLivenessAnalysis)

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

        self.analyses_cache.invalidate_analysis(MemLivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)

    def _handle_bb(self, bb: IRBasicBlock):
        for inst in bb.instructions:
            if inst.opcode == "alloca":
                base_ptr = self.base_ptrs.ptr_from_op(inst.output)
                assert base_ptr is not None, f"alloca without base ptr: {inst}"
                assert self.allocator.is_allocated(
                    base_ptr.base_alloca
                ), f"alloca not allocated by livesets: {inst}"
                concrete = self.allocator.get_concrete(base_ptr)
                self.updater.replace(inst, "assign", [concrete])
