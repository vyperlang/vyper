from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysesCache, IRAnalysis
from vyper.venom.basicblock import IRInstruction, IRLabel
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction


class FCGAnalysis(IRAnalysis):
    """
    Compute the function call graph for the context.
    Only analyzes functions reachable from entry.
    """

    ctx: IRContext
    call_sites: dict[IRFunction, OrderedSet[IRInstruction]]
    callees: dict[IRFunction, OrderedSet[IRFunction]]
    _reachable: OrderedSet[IRFunction]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.ctx = function.ctx
        self.call_sites = dict()
        self.callees = dict()
        self._reachable = OrderedSet()

    def analyze(self) -> None:
        # Single-pass DFS from entry: build call graph and reachability together
        entry = self.ctx.entry_function
        assert entry is not None
        stack = [entry]
        while stack:
            fn = stack.pop()
            if fn in self._reachable:
                continue
            self._reachable.add(fn)
            self.call_sites.setdefault(fn, OrderedSet())
            self.callees[fn] = OrderedSet()

            for bb in fn.get_basic_blocks():
                for inst in bb.instructions:
                    if inst.opcode == "invoke":
                        label = inst.operands[0]
                        assert isinstance(label, IRLabel)
                        callee = self.ctx.get_function(label)
                        self.callees[fn].add(callee)
                        self.call_sites.setdefault(callee, OrderedSet()).add(inst)
                        stack.append(callee)

    def get_call_sites(self, fn: IRFunction) -> OrderedSet[IRInstruction]:
        return self.call_sites.get(fn, OrderedSet())

    def get_callees(self, fn: IRFunction) -> OrderedSet[IRFunction]:
        return self.callees.get(fn, OrderedSet())

    def get_reachable_functions(self) -> OrderedSet[IRFunction]:
        return self._reachable

    def get_unreachable_functions(self) -> list[IRFunction]:
        return [fn for fn in self.ctx.get_functions() if fn not in self._reachable]

    def invalidate(self):
        pass
