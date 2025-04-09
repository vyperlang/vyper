from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysesCache, IRAnalysis
from vyper.venom.basicblock import IRInstruction, IRLabel
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction


class FCGAnalysis(IRAnalysis):
    """
    Compute the function call graph for the context.
    """

    ctx: IRContext
    call_sites: dict[IRFunction, OrderedSet[IRInstruction]]
    callees: dict[IRFunction, OrderedSet[IRFunction]]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.ctx = function.ctx
        self.call_sites = dict()
        self.callees = dict()

    def analyze(self) -> None:
        ctx = self.ctx
        for func in ctx.get_functions():
            self.call_sites[func] = OrderedSet()
            self.callees[func] = OrderedSet()

        for fn in ctx.get_functions():
            self._analyze_function(fn)

    def get_call_sites(self, fn: IRFunction) -> OrderedSet[IRInstruction]:
        return self.call_sites.get(fn, OrderedSet())

    def get_callees(self, fn: IRFunction) -> OrderedSet[IRFunction]:
        return self.callees[fn]

    def _analyze_function(self, fn: IRFunction) -> None:
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "invoke":
                    label = inst.operands[0]
                    assert isinstance(label, IRLabel)  # mypy help
                    callee = self.ctx.get_function(label)
                    self.callees[fn].add(callee)
                    self.call_sites[callee].add(inst)

    def invalidate(self):
        pass
