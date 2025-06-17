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
    cfg: CFGAnalysis

    def analyze(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        all_variables = OrderedSet()
        for bb in self.function.get_basic_blocks():
            all_variables.update(bb.get_assignments())

        # the variables that are defined up to (but not including) this point
        self.defined_vars = dict()

        # variables that are defined at the output of the basic block
        self.defined_vars_bb = {bb: all_variables.copy() for bb in self.function.get_basic_blocks()}

        worklist = OrderedSet(self.function.get_basic_blocks())
        while len(worklist) > 0:
            bb = worklist.pop()
            changed = self._handle_bb(bb)

            if changed:
                worklist.update(self.cfg.cfg_out(bb))

    def _handle_bb(self, bb: IRBasicBlock) -> bool:
        # note that the any basic block with no predecessors
        # (either the function entry or the entry block to an unreachable
        # subgraph) will seed with empty. therefore, the fixed point will
        # keep refining down as we iterate over the lattice.
        input_defined = [self.defined_vars_bb[in_bb] for in_bb in self.cfg.cfg_in(bb)]
        bb_defined: OrderedSet[IRVariable]
        if len(input_defined) == 0:
            # special case for intersection()
            bb_defined = OrderedSet()
        else:
            bb_defined = OrderedSet.intersection(*input_defined)

        for inst in bb.instructions:
            self.defined_vars[inst] = bb_defined.copy()

            if inst.output is not None:
                bb_defined.add(inst.output)

        if self.defined_vars_bb[bb] != bb_defined:
            self.defined_vars_bb[bb] = bb_defined
            return True

        return False
