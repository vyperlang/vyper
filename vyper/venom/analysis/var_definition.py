from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRVariable


class VarDefinition(IRAnalysis):
    """
    Find the variables that whose definitions are available at every
    point in the program
    """

    defined_vars: dict[IRInstruction, OrderedSet[IRVariable]]
    defined_vars_bb: dict[IRLabel, OrderedSet[IRVariable]]

    def analyze(self):
        cfg: CFGAnalysis = self.analyses_cache.request_analysis(CFGAnalysis)  # type: ignore

        # the variables that are defined up to (but not including) this point
        self.defined_vars = dict()

        # variables that are defined at the output of the basic block
        self.defined_vars_bb = dict()

        # heuristic: faster if we seed with the dfs prewalk
        worklist = OrderedSet(cfg.dfs_post_walk)
        while len(worklist) > 0:
            bb = worklist.pop()
            changed = self._handle_bb(bb)

            if changed:
                worklist.update(bb.cfg_out)

    def _handle_bb(self, bb: IRBasicBlock) -> bool:
        bb_defined: OrderedSet[IRVariable]
        if len(bb.cfg_in) == 0:
            # special case for intersection()
            bb_defined: OrderedSet[IRVariable] = OrderedSet()
        else:
            bb_defined = OrderedSet.intersection(
                *(
                    self.defined_vars_bb[in_bb.label]
                    for in_bb in bb.cfg_in
                    if in_bb.label in self.defined_vars_bb
                )
            )

        for inst in bb.instructions:
            self.defined_vars[inst] = bb_defined.copy()

            if inst.output is not None:
                bb_defined.add(inst.output)

        if bb.label not in self.defined_vars_bb or self.defined_vars_bb[bb.label] != bb_defined:
            self.defined_vars_bb[bb.label] = bb_defined
            return True

        return False
