from __future__ import annotations

from dataclasses import dataclass

from vyper.venom.analysis.analysis import IRGlobalAnalysis
from vyper.venom.basicblock import IRLabel
from vyper.venom.function import IRFunction

# raw FMP opcodes: a function containing any of these touches the FMP and
# needs it threaded by FmpLoweringPass.
_RAW_FMP_TOUCH_OPS = frozenset(["dalloca", "dret", "getfmp", "setfmp", "retfmp"])

# raw publishing terminators: the publish fact lives in the terminator
# opcode. `dret` (raw) and `retfmp` (desugared) both make the caller adopt
# the callee's FMP.
_RAW_PUBLISH_OPS = frozenset(["dret", "retfmp"])


@dataclass(frozen=True)
class DynamicMemoryInfo:
    # the function touches the FMP, directly (raw FMP opcodes) or
    # transitively (it invokes a function that needs the FMP)
    needs_fmp: bool
    # the function publishes its FMP to the caller (the caller adopts it
    # as a hidden extra return value after lowering)
    publishes: bool


_EMPTY_INFO = DynamicMemoryInfo(needs_fmp=False, publishes=False)


class DynamicMemoryAnalysis(IRGlobalAnalysis):
    """
    The FMP touches-closure: which functions need the free-memory pointer
    threaded, and which publish it to their caller.

    For functions whose convention has been frozen (`fn._fmp_signature` is
    set -- by FmpLoweringPass/FmpPrunePass or by the parsed function-header
    annotation) the signature is authoritative. For unsealed (raw)
    functions the facts are syntactic scans (`needs_fmp` from the raw FMP
    opcodes, `publishes` from the publishing terminators) closed under an
    order-insensitive transitive fixpoint over invokes. The fixpoint stays
    load-bearing for cycle-correctness: the callee-first pass driver breaks
    call-graph cycles arbitrarily, so frozen-callee-first reads alone would
    miscompile on cycles -- a cycle member must conservatively thread the
    FMP even when its (not-yet-lowered) callees' shapes are unknown.
    """

    infos: dict[IRFunction, DynamicMemoryInfo]

    def analyze(self):
        functions = tuple(self.ctx.get_functions())

        needs_fmp: dict[IRFunction, bool] = {}
        publishes: dict[IRFunction, bool] = {}
        for fn in functions:
            sig = fn._fmp_signature
            if sig is not None:
                # frozen signature is authoritative; the function neither
                # gains a hidden FMP param via the closure nor loses one
                needs_fmp[fn] = sig.has_fmp_param or sig.publishes
                publishes[fn] = sig.publishes
            else:
                needs_fmp[fn] = self._touches_fmp(fn)
                publishes[fn] = self._publishes(fn)

        # order-insensitive transitive fixpoint over invokes
        changed = True
        while changed:
            changed = False
            for fn in functions:
                if fn._fmp_signature is not None or needs_fmp[fn]:
                    continue
                if any(needs_fmp.get(callee, False) for callee in self._iter_callees(fn)):
                    needs_fmp[fn] = True
                    changed = True

        self.infos = {
            fn: DynamicMemoryInfo(needs_fmp=needs_fmp[fn], publishes=publishes[fn])
            for fn in functions
        }

    def get_info(self, fn: IRFunction) -> DynamicMemoryInfo:
        return self.infos.get(fn, _EMPTY_INFO)

    def function_needs_fmp(self, fn: IRFunction) -> bool:
        return self.get_info(fn).needs_fmp

    def _touches_fmp(self, fn: IRFunction) -> bool:
        return any(
            inst.opcode in _RAW_FMP_TOUCH_OPS
            for bb in fn.get_basic_blocks()
            for inst in bb.instructions
        )

    def _publishes(self, fn: IRFunction) -> bool:
        return any(
            inst.opcode in _RAW_PUBLISH_OPS
            for bb in fn.get_basic_blocks()
            for inst in bb.instructions
        )

    def _iter_callees(self, fn: IRFunction):
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "invoke" or len(inst.operands) == 0:
                    continue
                target = inst.operands[0]
                if not isinstance(target, IRLabel):
                    continue
                callee = fn.ctx.functions.get(target)
                if callee is not None:
                    yield callee
