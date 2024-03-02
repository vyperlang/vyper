from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class SCCP(IRPass):

    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock) -> int:
        pass
