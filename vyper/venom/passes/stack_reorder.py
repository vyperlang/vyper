from vyper.utils import OrderedSet
from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.pass_manager import IRPassManager


class StackReorderPass(IRPass):
    visited: OrderedSet

    def __init__(self, manager: IRPassManager):
        super().__init__(manager)

    def _reorder_stack(self):
        pass

    def _visit(self, bb: IRBasicBlock):
        if bb in self.visited:
            return
        self.visited.add(bb)

        for bb_out in bb.cfg_out:
            self._visit(bb_out)

    def _run_pass(self):
        entry = self.manager.function.basic_blocks[0]
        self.visited = OrderedSet()
        self._visit(entry)
