from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock


class MustHaltAnalysis(IRAnalysis):
    """
    Find blocks from which every CFG path ends the current message call.

    The least fixed point intentionally excludes cycles: a loop with a
    halting exit is not guaranteed to take that exit.
    """

    cfg: CFGAnalysis
    must_halt: frozenset[IRBasicBlock]

    def analyze(self) -> None:
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        result = {bb for bb in self.function.get_basic_blocks() if bb.is_halting}

        # DFS postorder visits every acyclic successor before its predecessor.
        # A successor reached through a back edge remains absent, deliberately
        # excluding cycles from the least fixed point.
        for bb in self.cfg.dfs_post_walk:
            successors = self.cfg.cfg_out(bb)
            if (
                bb not in result
                and len(successors) > 0
                and all(succ in result for succ in successors)
            ):
                result.add(bb)

        self.must_halt = frozenset(result)

    def __contains__(self, bb: IRBasicBlock) -> bool:
        return bb in self.must_halt

    def invalidate(self) -> None:
        # Imported lazily to avoid an analysis-package import cycle.
        from vyper.venom.stack_safety import StackCleanupSafety

        del self.must_halt
        del self.cfg
        self.analyses_cache.invalidate_analysis(StackCleanupSafety)
