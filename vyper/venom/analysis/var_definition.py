from collections import defaultdict

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable


class VarDefinition(IRAnalysis):
    """
    Find the variables that whose definitions are available at every
    point in the program
    """

    defined_vars: dict[IRInstruction, OrderedSet[IRVariable]]
    defined_vars_bb: dict[IRBasicBlock, OrderedSet[IRVariable]]

    def analyze(self):
        cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        # the variables that are defined up to (but not including) this point
        self.defined_vars = dict()

        # variables that are defined at the output of the basic block
        self.defined_vars_bb = defaultdict(OrderedSet)

        # heuristic: faster if we seed with the dfs prewalk
        worklist = OrderedSet(cfg.dfs_pre_walk)
        while len(worklist) > 0:
            bb = worklist.pop()
            changed = self._handle_bb(bb)

            if changed:
                worklist.update(bb.cfg_out)

    def _handle_bb(self, bb: IRBasicBlock) -> bool:
        bb_defined: OrderedSet[IRVariable]
        if len(bb.cfg_in) == 0:
            # special case for intersection()
            bb_defined = OrderedSet()
        else:
            bb_defined = OrderedSet.intersection(
                *(self.defined_vars_bb[in_bb] for in_bb in bb.cfg_in)
            )

        for inst in bb.instructions:
            self.defined_vars[inst] = bb_defined.copy()

            if inst.output is not None:
                bb_defined.add(inst.output)

        if self.defined_vars_bb[bb] != bb_defined:
            self.defined_vars_bb[bb] = bb_defined
            return True

        return False
