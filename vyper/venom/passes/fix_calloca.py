from collections import deque

from vyper.venom.analysis import DFGAnalysis, FCGAnalysis
from vyper.venom.basicblock import IRInstruction, IRLabel, IRLiteral
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRGlobalPass
from vyper.venom.passes.machinery.inst_updater import InstUpdater


class FixCalloca(IRGlobalPass):
    def run_pass(self):
        for fn in self.ctx.get_functions():
            self.fcg = self.analyses_caches[fn].request_analysis(FCGAnalysis)
            self.dfg = self.analyses_caches[fn].request_analysis(DFGAnalysis)
            self.updater = InstUpdater(self.dfg)
            self._handle_fn(fn)

    def _handle_fn(self, fn: IRFunction):
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "calloca":
                    continue

                assert len(inst.operands) == 3
                size, _id, callsite = inst.operands
                assert isinstance(callsite, IRLabel)
                assert isinstance(_id, IRLiteral)

                called_name = callsite.value.rsplit("_call", maxsplit=1)[0]

                called = self.ctx.get_function(IRLabel(called_name))
                if _id.value not in called.allocated_args:
                    self._removed_unused_calloca(inst)
                    continue
                memloc = called.allocated_args[_id.value]

                inst.operands = [memloc, _id]

    def _removed_unused_calloca(self, inst: IRInstruction):
        to_remove = set()
        worklist: deque = deque()
        worklist.append(inst)
        while len(worklist) > 0:
            curr = worklist.popleft()
            if curr in to_remove:
                continue
            to_remove.add(curr)

            if curr.has_outputs:
                uses = self.dfg.get_uses(curr.output)
                worklist.extend(uses)

        self.updater.nop_multi(to_remove)
