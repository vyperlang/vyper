from vyper.utils import OrderedSet
from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.passes.base_pass import IRPass


class StackReorderPass(IRPass):
    visited: OrderedSet

    def _reorder_stack(self):
        pass

    def _visit(self, bb: IRBasicBlock):
        if bb in self.visited:
            return
        self.visited.add(bb)

        for bb_out in bb.cfg_out:
            self._visit(bb_out)

    def _run_pass(self):
        entry = self.function.entry
        self.visited = OrderedSet()
        self._visit(entry)
