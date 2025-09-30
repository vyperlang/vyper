from vyper.venom.analysis import FCGAnalysis
from vyper.venom.basicblock import IRAbstractMemLoc, IRLabel, IRLiteral
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRGlobalPass


class FixCalloca(IRGlobalPass):
    def run_pass(self):
        for fn in self.ctx.get_functions():
            self.fcg = self.analyses_caches[fn].request_analysis(FCGAnalysis)
            self._handle_fn(fn)

    def _handle_fn(self, fn: IRFunction):
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "calloca":
                    continue

                assert inst.output is not None
                assert len(inst.operands) == 3
                size, _id, callsite = inst.operands
                assert isinstance(callsite, IRLabel)
                assert isinstance(_id, IRLiteral)

                called_name = callsite.value.rsplit("_call", maxsplit=1)[0]

                called = self.ctx.get_function(IRLabel(called_name))
                if _id.value not in called.allocated_args:
                    # TODO in this case the calloca should be removed I think
                    inst.operands = [IRAbstractMemLoc(size.value, inst), _id]
                    continue
                memloc = called.allocated_args[_id.value]

                inst.operands = [memloc, _id]
