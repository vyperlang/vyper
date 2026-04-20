from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLabel, IRVariable
from vyper.venom.passes.base_pass import IRPass


class DallocaStackThreading(IRPass):
    """
    Thread the free-memory pointer (FMP) as a plain SSA value through
    every function that uses `dalloca` (directly or transitively via
    `invoke`). Runs pre-SSA: each dalloca in a needs-fmp function is
    rewritten from single-output (`%p = dalloca %size`) to dual-output
    (`%p, %fmp = dalloca %fmp, %size`) where the first output is the
    allocated pointer and the second is the advanced FMP. Each invoke
    to a needs-fmp callee takes the caller's current fmp as the first
    (deepest-on-stack) argument. A subsequent MakeSSA run renames the
    reassignments into fresh SSA versions and places phis at merge
    points.

    The callee does not propagate FMP back to the caller; the caller's
    FMP SSA variable survives across `invoke` via standard liveness
    (the stack scheduler DUPs it before the call when needed). This
    implicitly reclaims the callee's dynamically allocated memory when
    the callee returns.

    Invariant used for scheduling: this pass runs per-function in
    callee-first order, so by the time we process a caller, every
    callee's `_needs_fmp` flag is set. See `_run_fn_passes_r` in
    `vyper/venom/__init__.py` for the scheduling order.
    """

    required_predecessors = ("DallocaPromotion",)

    def run_pass(self):
        fn = self.function

        # determine needs_fmp: function has a dalloca, or invokes a
        # needs_fmp callee.
        has_dalloca = any(
            inst.opcode == "dalloca" for bb in fn.get_basic_blocks() for inst in bb.instructions
        )

        calls_needs_fmp = False
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "invoke":
                    continue
                target = inst.operands[0]
                assert isinstance(target, IRLabel)
                callee = fn.ctx.functions.get(target)
                if callee is not None and getattr(callee, "_needs_fmp", False):
                    calls_needs_fmp = True
                    break
            if calls_needs_fmp:
                break

        needs_fmp = has_dalloca or calls_needs_fmp
        fn._needs_fmp = needs_fmp  # type: ignore[attr-defined]

        if not needs_fmp:
            return

        # single variable representing the threaded FMP across the
        # whole function in pre-SSA form. All re-definitions share
        # this name; MakeSSA will version them and insert phis at
        # merge points.
        fmp_var = fn.get_next_variable()

        # add leading `param` at entry, before any other instructions.
        entry = fn.entry
        param_inst = IRInstruction("param", [], [fmp_var])
        param_inst.parent = entry
        entry.instructions.insert(0, param_inst)

        # rewrite dallocas and invokes in program order per basic block.
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "dalloca":
                    self._rewrite_dalloca(inst, fmp_var)
                elif inst.opcode == "invoke":
                    target = inst.operands[0]
                    assert isinstance(target, IRLabel)
                    callee = fn.ctx.functions.get(target)
                    if callee is not None and getattr(callee, "_needs_fmp", False):
                        self._augment_invoke(inst, fmp_var)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _rewrite_dalloca(self, inst: IRInstruction, fmp_var: IRVariable) -> None:
        # Before: single output, one operand (size). Parser convention:
        #   `%p = dalloca %size`  ->  operands=[%size], outputs=[%p]
        # After: dual output, two operands (fmp, size). TOS is size.
        #   `%p, %fmp = dalloca %fmp, %size`
        #   operands=[fmp, size], outputs=[ptr, fmp]
        assert inst.num_outputs == 1, inst
        assert len(inst.operands) == 1, inst
        size = inst.operands[0]
        ptr_out = inst.output
        inst.operands = [fmp_var, size]
        inst.set_outputs([ptr_out, fmp_var])

    def _augment_invoke(self, inst: IRInstruction, fmp_var: IRVariable) -> None:
        # Invoke's internal operand layout (after parser reversal):
        #   operands[0] = target label
        #   operands[1] = arg-pushed-first = deepest below return_label
        #   operands[-1] = arg-pushed-last = TOS below return_label
        # The callee's params pop in textual order, so the first `param`
        # instruction takes the *deepest* caller arg. To make fmp the
        # deepest arg (matching the leading `param` we inject in the
        # callee), fmp must be at operands[1], immediately after the
        # target label.
        # Note: we intentionally do NOT model invoke as returning a new
        # fmp value. The caller's fmp SSA variable survives the invoke
        # via liveness; the callee's dynamically allocated memory is
        # reclaimed simply by returning (our ret doesn't propagate fmp
        # back, so the caller's next dalloca reuses that memory).
        inst.operands = [inst.operands[0], fmp_var] + inst.operands[1:]
