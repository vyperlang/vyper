from vyper.utils import evm_not
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.passes.base_pass import IRPass


class DallocaLoweringPass(IRPass):
    """
    Lower `dalloca` into explicit FMP-threaded arithmetic using the
    primitive `bump` op.

    Responsibilities:
      1. Thread the free-memory pointer (FMP) as a plain SSA value
         through every function that uses `dalloca` (directly or
         transitively via `invoke`).
      2. Rewrite each `%p = dalloca %size` into:
             %a       = add %size, 31
             %aligned = and %a, 0xff..e0      ; ceil32(size)
             %p, %fmp = bump %fmp, %aligned
         where the `%fmp` on the right is the current FMP SSA value in
         the threading chain and the output `%fmp` is the next one.
         `bump` is a pure arithmetic primitive: `bump a, b` returns
         `(a, a + b)`.

    After this pass, no `dalloca` instructions remain in the IR.

    Runs pre-SSA: a single shared `fmp_var` is re-assigned at each
    `bump`. A subsequent MakeSSA run renames the reassignments into
    fresh SSA versions and places phis at merge points.

    Each invoke to a needs-fmp callee takes the caller's current fmp
    as the first (deepest-on-stack) argument. The callee does not
    propagate FMP back to the caller; the caller's FMP SSA variable
    survives across `invoke` via standard liveness (the stack
    scheduler DUPs it before the call when needed). This implicitly
    reclaims the callee's dynamically allocated memory when the
    callee returns.

    `_needs_fmp` is computed per-function in callee-first order: a function
    needs fmp if it contains a `dalloca` OR it invokes a callee that already
    has `_needs_fmp` set. This is sound because Vyper's frontend rejects all
    cyclic function calls at semantic analysis time (see
    `vyper/semantics/analysis/module.py::_compute_reachable_set`, which raises
    CallViolation on any recursion — self, direct, or indirect). The call
    graph reaching this pass is therefore a DAG, and callee-first traversal
    in `_run_fn_passes_r` populates flags in topological order.
    """

    required_predecessors = ("DallocaPromotion",)
    required_successors = ("MakeSSA",)

    def run_pass(self):
        fn = self.function

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
                callee = fn.ctx.get_function(target)
                if callee._needs_fmp:
                    calls_needs_fmp = True
                    break
            if calls_needs_fmp:
                break

        fn._needs_fmp = has_dalloca or calls_needs_fmp

        if not fn._needs_fmp:
            return

        # single variable representing the threaded FMP across the
        # whole function in pre-SSA form. All re-definitions share
        # this name; MakeSSA will version them and insert phis at
        # merge points.
        fmp_var = fn.get_next_variable()

        # add leading `param` at entry, before any other instructions.
        param_inst = IRInstruction("param", [], [fmp_var])
        fn.entry.insert_instruction(param_inst, index=0)

        # rewrite dallocas and invokes in program order per basic block.
        for bb in fn.get_basic_blocks():
            self._rewrite_bb(bb, fn, fmp_var)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _rewrite_bb(self, bb, fn, fmp_var: IRVariable) -> None:
        new_instructions: list[IRInstruction] = []
        for inst in bb.instructions:
            if inst.opcode == "dalloca":
                new_instructions.extend(self._lower_dalloca(inst, fn, fmp_var, bb))
                continue
            if inst.opcode == "invoke":
                target = inst.operands[0]
                assert isinstance(target, IRLabel)
                callee = fn.ctx.get_function(target)
                if callee._needs_fmp:
                    self._augment_invoke(inst, fmp_var)
            new_instructions.append(inst)
        bb.instructions = new_instructions

    def _lower_dalloca(
        self, inst: IRInstruction, fn, fmp_var: IRVariable, bb
    ) -> list[IRInstruction]:
        # Before: `%p = dalloca %size` -> operands=[%size], outputs=[%p].
        # After (sequence):
        #   %a       = add %size, 31
        #   %aligned = and %a, 0xff..e0
        #   %p, %fmp = bump %fmp, %aligned
        assert inst.num_outputs == 1, inst
        assert len(inst.operands) == 1, inst
        size = inst.operands[0]
        ptr_out = inst.output

        a_var = fn.get_next_variable()
        aligned_var = fn.get_next_variable()

        # venom operand convention: rightmost operand is TOS.
        add_inst = IRInstruction("add", [IRLiteral(31), size], [a_var])
        and_inst = IRInstruction("and", [IRLiteral(evm_not(31)), a_var], [aligned_var])
        # `bump a, b` -> outputs (a, a+b). operands=[fmp, aligned] means
        # fmp is deepest (operands[0]) and aligned is TOS (operands[-1]),
        # matching Venom's stack convention.
        bump_inst = IRInstruction("bump", [fmp_var, aligned_var], [ptr_out, fmp_var])

        for new_inst in (add_inst, and_inst, bump_inst):
            new_inst.parent = bb
            new_inst.ast_source = inst.ast_source
            new_inst.error_msg = inst.error_msg

        return [add_inst, and_inst, bump_inst]

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
