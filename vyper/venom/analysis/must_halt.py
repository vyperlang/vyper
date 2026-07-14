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
        blocks = tuple(self.function.get_basic_blocks())
        result = {bb for bb in blocks if bb.is_halting}

        changed = True
        while changed:
            changed = False
            for bb in blocks:
                successors = self.cfg.cfg_out(bb)
                if bb not in result and successors and all(succ in result for succ in successors):
                    result.add(bb)
                    changed = True

        self.must_halt = frozenset(result)

    def __contains__(self, bb: IRBasicBlock) -> bool:
        return bb in self.must_halt

    def invalidate(self) -> None:
        del self.must_halt
        del self.cfg
