from vyper.utils import MemoryPositions
from vyper.venom.analysis import DFGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IRVariable
from vyper.venom.memory_location import (
    Allocation,
    get_memory_read_op,
    get_memory_write_op,
    get_read_size,
    get_write_max_size,
    update_read_location,
    update_write_location,
)
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.machinery.inst_updater import InstUpdater


def in_free_var(free_var, offset):
    return offset >= free_var and offset < (free_var + 32)


class FixMemLocationsPass(IRPass):
    """
    Pass that fixes cases of memory accesses where the target of read/write is
    in the range of MemoryPosition.FREE_VAR_SPACE and MemoryPosition.FREE_VAR_SPACE2
    and replaces it by pinned allocation (allocation that is done with the alloca but
    is pinned to specific position)
    """

    free_ptr1: IRVariable
    free_ptr2: IRVariable
    # Pinned allocas introduced here must be concretized before lowering/codegen.
    required_successors = ("ConcretizeMemLocPass",)

    def run_pass(self):
        # this dfg is here just for the updater since this is run before the
        # MakeSSA it is not necessarily correct, but for the cases that are
        # needed here it should be correct
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

    def _process_bb(self, bb: IRBasicBlock):
        for inst in bb.instructions:
            write_op = get_memory_write_op(inst)
            read_op = get_memory_read_op(inst)
            if write_op is not None:
                size = get_write_max_size(inst)
                if size is not None and isinstance(write_op, IRLiteral):
                    assert False, (bb, inst)
            if read_op is not None:
                size = get_read_size(inst)
                if size is None or not isinstance(read_op, IRLiteral):
                    continue
                assert False, (bb, inst)
