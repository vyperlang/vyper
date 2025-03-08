from collections import defaultdict

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable


class VarDefinition(IRAnalysis):
    defined_vars: dict[IRInstruction, OrderedSet[IRVariable]]
    defined_vars_bb: dict[IRBasicBlock, OrderedSet[IRVariable]]

    def analyze(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.defined_vars = dict()
        self.defined_vars_bb = defaultdict(OrderedSet)
        while True:
            change = False
            for bb in self.function.get_basic_blocks():
                change |= self._handle_bb(bb)

            if not change:
                break

    def _handle_bb(self, bb: IRBasicBlock) -> bool:
        if len(bb.cfg_in) == 0:
            bb_defined = OrderedSet()
        else:
            bb_defined = OrderedSet.intersection(
                *(self.defined_vars_bb[in_bb] for in_bb in bb.cfg_in)
            )

        for inst in bb.instructions:
            if inst.output is not None:
                bb_defined.add(inst.output)

            self.defined_vars[inst] = bb_defined.copy()

        if self.defined_vars_bb[bb] != bb_defined:
            self.defined_vars_bb[bb] = bb_defined
            return True

        return False
