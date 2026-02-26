from vyper.venom.analysis import DFGAnalysis, FCGAnalysis
from vyper.venom.basicblock import IRLabel, IRLiteral
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRGlobalPass
from vyper.venom.passes.machinery.inst_updater import InstUpdater


class FixCalloca(IRGlobalPass):
    """
    Fix callocas after IR generation but before function inlining.
    Point to abstract memory locations and fixup ids so that they can
    be reified with the callee function.
    """

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
                if not called.has_palloca(_id.value):
                    to_remove = self.dfg.get_transitive_uses(inst)
                    self.updater.nop_multi(to_remove)
                    continue

                inst.operands = [size, _id, called.name]
