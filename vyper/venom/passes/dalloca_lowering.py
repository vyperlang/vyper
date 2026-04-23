from vyper.exceptions import CompilerPanic
from vyper.utils import evm_not
from vyper.venom.analysis import BasePtrAnalysis, DFGAnalysis, LivenessAnalysis, MemLivenessAnalysis
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

    `dfree %ptr` is high-level sugar that frees a prior `dalloca`. Within a
    basic block, dfrees pair with dallocas in LIFO order. Two lowerings:
      - **Rewire** (preferred): if nothing between the paired `bump` and the
        `dfree` observes `fmp_var`, drop the whole `bump` chain and substitute
        uses of `%ptr` with the pre-bump FMP. No runtime cost.
      - **Sub fallback**: if an intervening instruction reads `fmp_var`
        (e.g. a `bump` for a nested dalloca, or an `invoke` augmented with
        fmp), keep the original `bump` and emit `sub aligned, fmp -> fmp` at
        the dfree point to revert the FMP. One SUB byte.

    Fast path: if a function has dallocas but does NOT invoke a
    `_needs_fmp` callee, AND every dalloca/dfree pair in the function is
    strictly sequential (no two live at the same time), we lower each
    `dalloca` to `initial_fmp` (a compile-time constant pseudo-op that
    resolves to `max(global_max_fn_eom, peak_spill_end, RESERVED_MEMORY)`
    at assembly time) and drop each `dfree`. Since the allocations don't
    overlap in time, they can safely share the same base address. This
    avoids FMP threading entirely and keeps bytecode tight for the common
    single-use scratch pattern (raw_call, create_copy_of, etc.).
    """

    required_predecessors = ("ConcretizeMemLocPass",)
    required_successors = ("MakeSSA",)

    def run_pass(self):
        fn = self.function

        # Up-front validation: every `dfree` must pair with a `dalloca` in
        # the same BB (LIFO), and no use of a ptr is allowed after its
        # `dfree`. Catching this here keeps malformed IR from reaching
        # either the fast path or the FMP-threading path (both rely on
        # well-formed pairing).
        self._validate_dalloca_dfree(fn)

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

        if not has_dalloca and not calls_needs_fmp:
            fn._needs_fmp = False
            return

        # Fast path: if this function has dallocas but doesn't invoke any
        # needs-fmp callee, AND every dalloca has a paired dfree in the
        # same basic block with no overlapping (nested) allocations live
        # at any point, we can skip FMP threading entirely and lower each
        # `dalloca` to `initial_fmp` and drop each `dfree`. Two scratch
        # allocations that don't overlap in time can safely alias the
        # same base address, so a single compile-time constant suffices.
        if has_dalloca and not calls_needs_fmp and self._can_initial_fmp_lower(fn):
            self._initial_fmp_lower(fn)
            fn._needs_fmp = False
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)
            self.analyses_cache.invalidate_analysis(DFGAnalysis)
            self.analyses_cache.invalidate_analysis(BasePtrAnalysis)
            self.analyses_cache.invalidate_analysis(MemLivenessAnalysis)
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

        fn._needs_fmp = True

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)
        self.analyses_cache.invalidate_analysis(MemLivenessAnalysis)

    def _validate_dalloca_dfree(self, fn) -> None:
        """Panic on malformed dalloca/dfree patterns.

        Checks (per BB):
          - `dalloca` must have 1 operand and 1 output.
          - `dfree` must have exactly 1 operand.
          - Every `dfree` must pair with a preceding `dalloca` in the same
            BB (LIFO).
          - A ptr cannot be used after its matching `dfree`
            (use-after-free).

        Unpaired dallocas at BB boundaries are allowed: they survive to
        function return, where the FMP-threading mechanism reclaims them
        implicitly via SSA liveness (the caller's fmp_var SSA variable is
        untouched by the invoke).
        """
        for bb in fn.get_basic_blocks():
            open_ptrs: list[IRVariable] = []
            freed_ptrs: set[IRVariable] = set()
            for inst in bb.instructions:
                if inst.opcode == "dalloca":
                    if inst.num_outputs != 1 or len(inst.operands) != 1:
                        raise CompilerPanic(
                            f"dalloca must have 1 operand and 1 output: {inst}"
                        )
                    open_ptrs.append(inst.output)
                elif inst.opcode == "dfree":
                    if len(inst.operands) != 1:
                        raise CompilerPanic(f"dfree must have exactly 1 operand: {inst}")
                    if not open_ptrs:
                        raise CompilerPanic(
                            f"dfree without matching dalloca in same basic block: {inst}"
                        )
                    if open_ptrs[-1] != inst.operands[0]:
                        raise CompilerPanic(
                            f"dfree LIFO violation: expected {open_ptrs[-1]}, "
                            f"got {inst.operands[0]}: {inst}"
                        )
                    freed_ptrs.add(open_ptrs.pop())
                else:
                    # Any other instruction using a freed ptr as an operand
                    # is a use-after-free. Skip `invoke`'s first operand
                    # (a label, not a value).
                    start = 1 if inst.opcode == "invoke" else 0
                    for op in inst.operands[start:]:
                        if op in freed_ptrs:
                            raise CompilerPanic(f"use of dfree'd pointer {op}: {inst}")

    def _can_initial_fmp_lower(self, fn) -> bool:
        """True if the initial_fmp fast path is safe for this function.

        The fast path replaces `dalloca` with a constant load of the
        contract-wide initial FMP. Multiple functions all resolving to
        the same constant is safe ONLY if their uses of that address
        never overlap in time. Call-graph reasoning for this is complex;
        we use a strict conservative rule instead:

          - The function must have no `invoke` instructions.

        Rationale: if F has any invoke I, then during I the callee may
        itself take this fast path and write to the same `initial_fmp`
        address that F wrote to. Even if F's own dallocas are all freed
        before I, any data F stored at fmp-based addresses (from rewire
        or entry-function bumps) could be clobbered by the callee. The
        FMP-threaded path does not have this issue because each frame
        threads a distinct, advanced fmp value.

        Additional per-BB requirements (for lowering correctness):
          - Every `dalloca` has a paired `dfree` in the same BB. Un-paired
            dallocas that escape the BB need the FMP-threaded path.
          - No two dallocas are live at the same time (no nesting).
            Overlapping lifetimes would alias the same base address.

        Assumes `_validate_dalloca_dfree` already enforced LIFO pairing
        and no-use-after-free.
        """
        for bb in fn.get_basic_blocks():
            live_count = 0
            for inst in bb.instructions:
                if inst.opcode == "dalloca":
                    if live_count > 0:
                        return False  # nesting
                    live_count += 1
                elif inst.opcode == "dfree":
                    live_count -= 1
                elif inst.opcode == "invoke":
                    return False  # interprocedural safety
            if live_count > 0:
                return False  # un-paired dalloca at end of BB
        return True

    def _initial_fmp_lower(self, fn) -> None:
        """Replace every `dalloca %size` with `%p = initial_fmp` and drop
        every `dfree`. `initial_fmp` is a pure compile-time constant (the
        initial FMP value); since this path requires non-overlapping
        allocations, all scratches safely share the same base address.
        Emitting a fresh `initial_fmp` at each use (rather than hoisting to
        the function entry) avoids forcing the scheduler to keep the value
        live across the whole function, which would cause spills in
        stack-pressured functions.

        Both rewrites are in-place: `dalloca` and `initial_fmp` have the
        same output arity so we just swap the opcode and drop operands;
        `dfree` becomes a nop.
        """
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "dalloca":
                    inst.opcode = "initial_fmp"
                    inst.operands = []
                elif inst.opcode == "dfree":
                    inst.make_nop()

    def _rewrite_bb(self, bb, fn, fmp_var: IRVariable) -> None:
        new_instructions: list[IRInstruction] = []
        # LIFO stack of open `dalloca`s awaiting their paired `dfree`.
        # Each entry: {ptr, bump_insts: (add, and, bump), aligned_var}.
        bump_stack: list[dict] = []

        for inst in bb.instructions:
            if inst.opcode == "dalloca":
                lowered = self._lower_dalloca(inst, fn, fmp_var, bb)
                bump_stack.append(
                    {
                        "ptr": inst.output,
                        "bump_insts": tuple(lowered),
                        "aligned_var": lowered[1].output,
                    }
                )
                new_instructions.extend(lowered)
                continue

            if inst.opcode == "dfree":
                self._lower_dfree(inst, fmp_var, bb, bump_stack, new_instructions)
                continue

            if inst.opcode == "invoke":
                target = inst.operands[0]
                assert isinstance(target, IRLabel)
                callee = fn.ctx.get_function(target)
                if callee._needs_fmp:
                    self._augment_invoke(inst, fmp_var)
            new_instructions.append(inst)

        bb.instructions = new_instructions

    def _lower_dfree(
        self,
        inst: IRInstruction,
        fmp_var: IRVariable,
        bb,
        bump_stack: list[dict],
        new_instructions: list[IRInstruction],
    ) -> None:
        if len(inst.operands) != 1:
            raise CompilerPanic(f"dfree must have exactly 1 operand: {inst}")
        if not bump_stack:
            raise CompilerPanic(f"dfree without matching dalloca in same basic block: {inst}")
        entry = bump_stack.pop()
        if inst.operands[0] != entry["ptr"]:
            raise CompilerPanic(
                f"dfree LIFO violation: expected {entry['ptr']}, got {inst.operands[0]}: {inst}"
            )

        bump_inst = entry["bump_insts"][-1]
        bump_idx = new_instructions.index(bump_inst)

        # Safe to rewire iff nothing after the bump:
        #   (a) reads fmp_var — dropping the bump would change its meaning; or
        #   (b) is an `invoke` — rewiring leaves the ptr at fmp_var, which
        #       may equal `initial_fmp` (entry function) or overlap a
        #       fast-path callee's allocation, causing cross-frame aliasing.
        #       Keeping the bump makes the ptr sit at a strictly-below-fmp
        #       address that callees starting from a larger fmp cannot reach.
        tainted = any(
            fmp_var in new_instructions[i].operands
            or new_instructions[i].opcode == "invoke"
            for i in range(bump_idx + 1, len(new_instructions))
        )

        if not tainted:
            # Rewire: drop the (add, and, bump) chain and substitute uses of
            # the ptr with the pre-bump fmp_var.
            for to_remove in entry["bump_insts"]:
                new_instructions.remove(to_remove)
            ptr_name = entry["ptr"]
            for other in new_instructions:
                other.operands = [fmp_var if op == ptr_name else op for op in other.operands]
            return

        # Fallback: emit `sub aligned, fmp -> fmp` to revert the FMP. Venom
        # operand convention: rightmost is TOS. EVM SUB computes TOS - next,
        # so `sub aligned, fmp` yields `fmp - aligned = pre_bump_fmp`.
        sub_inst = IRInstruction("sub", [entry["aligned_var"], fmp_var], [fmp_var])
        sub_inst.parent = bb
        sub_inst.ast_source = inst.ast_source
        sub_inst.error_msg = inst.error_msg
        new_instructions.append(sub_inst)

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
