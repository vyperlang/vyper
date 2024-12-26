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
    calls: dict[IRFunction, OrderedSet[IRInstruction]]
    callees: dict[IRFunction, OrderedSet[IRFunction]]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.ctx = function.ctx
        self.calls = dict()
        self.callees = dict()

    def analyze(self) -> None:
        ctx = self.ctx
        fn = self.function
        for func in ctx.get_functions():
            self.calls[func] = OrderedSet()
            self.callees[func] = OrderedSet()

        for fn in ctx.get_functions():
            self._analyze_function(fn)

    def get_calls(self, fn: IRFunction) -> OrderedSet[IRInstruction]:
        return self.calls[fn]

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
                    self.calls[callee].add(inst)

    def invalidate(self):
        pass