from vyper.utils import evm_not
from vyper.venom.analysis import BasePtrAnalysis, DFGAnalysis, LivenessAnalysis, MemLivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.call_layout import (
    FunctionCallLayout,
    InvokeLayout,
)
from vyper.venom.passes.base_pass import IRPass


class DallocaLoweringPass(IRPass):
    """
    Lower `dalloca` into explicit FMP-threaded arithmetic using `bump`.

    `dalloca` is a generic low-level region/cursor primitive. It takes one
    operand (`size`) and always produces:

      - `%ptr, %mark = dalloca %size`

    `%ptr` is the base address of the newly allocated `ceil32(size)`-byte
    region. `%mark` is a restore token equal to the pre-bump FMP. `dfree %mark`
    restores the current threaded FMP to that token; it does not model heap
    free semantics or pointer identity.

    Generic lowering:
      1. Thread the free-memory pointer (FMP) as a plain SSA value through
         every function that uses `dalloca` directly, or invokes a callee
         that already needs FMP threading.
      2. Rewrite each `dalloca` into:
             %a       = add %size, 31
             %aligned = and %a, 0xff..e0
             %ptr, %fmp = bump %fmp, %aligned
         and, for the 2-output form, materialize `%mark = assign %ptr`.
      3. Rewrite `dfree %mark` into `assign %mark -> %fmp`.

    Structured same-BB scratch patterns are optimized more aggressively:
      - If the function is the entry function, has no invokes, and every
        `dalloca/dfree` pair is same-BB, LIFO, and non-overlapping, each
        `dalloca` is folded to `initial_fmp` and each `dfree` is dropped.
      - In the threaded path, a same-BB top-of-stack `dfree` can rewire its
        matching allocation away entirely if nothing after the `bump` observes
        the advanced FMP or performs an `invoke`.

    Unpaired allocations are allowed. In that case the allocation stays live
    until function return, and caller/callee isolation still relies on the
    invoke boundary preserving the caller's threaded FMP.
    """

    required_successors = ("MakeSSA",)

    def run_pass(self):
        fn = self.function

        has_dalloca = any(
            inst.opcode == "dalloca" for bb in fn.get_basic_blocks() for inst in bb.instructions
        )
        has_dfree = any(
            inst.opcode == "dfree" for bb in fn.get_basic_blocks() for inst in bb.instructions
        )

        calls_needs_fmp = False
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "invoke":
                    continue
                callee = InvokeLayout(fn.ctx, inst).callee
                if callee is not None and callee._needs_fmp:
                    calls_needs_fmp = True
                    break
            if calls_needs_fmp:
                break

        if fn._has_fmp_param and not has_dalloca and not has_dfree:
            changed = self._deaugment_stale_invoke_fmp_args(fn)
            if changed:
                self._invalidate_analyses()

            if self._prune_dead_hidden_fmp_param(fn):
                fn._needs_fmp = False
                fn._has_fmp_param = False
                self._invalidate_analyses()
                return

            fn._needs_fmp = True
            fn._has_fmp_param = True
            return

        if not has_dalloca and not has_dfree and not calls_needs_fmp:
            fn._needs_fmp = False
            fn._has_fmp_param = False
            return

        if has_dalloca and self._can_initial_fmp_lower(fn):
            self._initial_fmp_lower(fn)
            fn._needs_fmp = False
            fn._has_fmp_param = False
            self._invalidate_analyses()
            return

        # Single pre-SSA variable representing the threaded FMP across the
        # whole function. MakeSSA will version this and place phis as needed.
        fmp_var = fn.get_next_variable()
        param_inst = IRInstruction("param", [], [fmp_var])
        fn.entry.insert_instruction(
            param_inst, index=FunctionCallLayout(fn).hidden_fmp_param_insert_index
        )

        for bb in fn.get_basic_blocks():
            self._rewrite_bb(bb, fn, fmp_var)

        fn._needs_fmp = True
        fn._has_fmp_param = True
        self._invalidate_analyses()

    def _invalidate_analyses(self) -> None:
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)
        self.analyses_cache.invalidate_analysis(MemLivenessAnalysis)

    def _restore_token(self, inst: IRInstruction) -> IRVariable:
        outs = inst.get_outputs()
        assert len(outs) == 2, inst
        return outs[-1]

    def _can_initial_fmp_lower(self, fn) -> bool:
        """
        True if the compact `initial_fmp` fast path is safe for this function.

        This path is intentionally conservative. It is restricted to the entry
        function so a fast-path callee cannot alias a caller's live dynamic
        allocation through the contract-wide `initial_fmp` constant.
        """
        if fn is not fn.ctx.entry_function:
            return False

        for bb in fn.get_basic_blocks():
            open_tokens: list[IRVariable] = []
            for inst in bb.instructions:
                if inst.opcode == "dalloca":
                    if open_tokens:
                        return False
                    open_tokens.append(self._restore_token(inst))
                elif inst.opcode == "dfree":
                    if not open_tokens or inst.operands[0] != open_tokens[-1]:
                        return False
                    open_tokens.pop()
                elif inst.opcode == "invoke":
                    return False
            if open_tokens:
                return False
        return True

    def _initial_fmp_lower(self, fn) -> None:
        for bb in fn.get_basic_blocks():
            new_instructions: list[IRInstruction] = []
            for inst in bb.instructions:
                if inst.opcode == "dalloca":
                    ptr_out = inst.get_outputs()[0]
                    mark_out = inst.get_outputs()[1]

                    init_inst = IRInstruction("initial_fmp", [], [ptr_out])
                    self._copy_metadata(inst, init_inst, bb)
                    new_instructions.append(init_inst)

                    mark_inst = IRInstruction("assign", [ptr_out], [mark_out])
                    self._copy_metadata(inst, mark_inst, bb)
                    new_instructions.append(mark_inst)
                    continue

                if inst.opcode == "dfree":
                    continue

                new_instructions.append(inst)

            bb.instructions = new_instructions

    def _rewrite_bb(self, bb, fn, fmp_var: IRVariable) -> None:
        new_instructions: list[IRInstruction] = []
        bump_stack: list[dict] = []

        for inst in bb.instructions:
            if inst.opcode == "dalloca":
                lowered, entry = self._lower_dalloca(inst, fn, fmp_var, bb)
                bump_stack.append(entry)
                new_instructions.extend(lowered)
                continue

            if inst.opcode == "dfree":
                self._lower_dfree(inst, fmp_var, bb, bump_stack, new_instructions)
                continue

            if inst.opcode == "invoke":
                callee = InvokeLayout(fn.ctx, inst).callee
                if callee is not None and callee._needs_fmp:
                    self._augment_invoke(inst, fmp_var)
            new_instructions.append(inst)

        bb.instructions = new_instructions

    def _restore_fmp_inst(
        self, mark: IROperand, fmp_var: IRVariable, bb, origin: IRInstruction
    ) -> IRInstruction:
        inst = IRInstruction("assign", [mark], [fmp_var])
        self._copy_metadata(origin, inst, bb)
        return inst

    def _rewire_entry(self, entry: dict, fmp_var: IRVariable, bb) -> list[IRInstruction]:
        ptr_alias = IRInstruction("assign", [fmp_var], [entry["ptr"]])
        self._copy_metadata(entry["origin"], ptr_alias, bb)

        mark_alias = IRInstruction("assign", [entry["ptr"]], [entry["mark"]])
        self._copy_metadata(entry["origin"], mark_alias, bb)
        return [ptr_alias, mark_alias]

    def _lower_dfree(
        self,
        inst: IRInstruction,
        fmp_var: IRVariable,
        bb,
        bump_stack: list[dict],
        new_instructions: list[IRInstruction],
    ) -> None:
        mark = inst.operands[0]
        top = bump_stack[-1] if bump_stack else None

        if top is None or mark != top["mark"]:
            # Unstructured restore. This is still valid low-level IR; it just
            # does not qualify for the local scratch rewrite.
            bump_stack.clear()
            new_instructions.append(self._restore_fmp_inst(mark, fmp_var, bb, inst))
            return

        entry = bump_stack.pop()
        first_idx = new_instructions.index(entry["introduced"][0])

        tainted = any(
            fmp_var in new_instructions[i].operands or new_instructions[i].opcode == "invoke"
            for i in range(first_idx + len(entry["introduced"]), len(new_instructions))
        )

        if not tainted:
            for to_remove in entry["introduced"]:
                new_instructions.remove(to_remove)
            new_instructions[first_idx:first_idx] = self._rewire_entry(entry, fmp_var, bb)
            return

        new_instructions.append(self._restore_fmp_inst(mark, fmp_var, bb, inst))

    def _lower_dalloca(self, inst: IRInstruction, fn, fmp_var: IRVariable, bb) -> tuple[list, dict]:
        assert len(inst.operands) == 1, inst
        assert inst.num_outputs == 2, inst

        size = inst.operands[0]
        ptr_out = inst.get_outputs()[0]
        mark_out = inst.get_outputs()[1]

        a_var = fn.get_next_variable()
        aligned_var = fn.get_next_variable()

        add_inst = IRInstruction("add", [IRLiteral(31), size], [a_var])
        and_inst = IRInstruction("and", [IRLiteral(evm_not(31)), a_var], [aligned_var])
        bump_inst = IRInstruction("bump", [fmp_var, aligned_var], [ptr_out, fmp_var])

        lowered = [add_inst, and_inst, bump_inst]
        for new_inst in lowered:
            self._copy_metadata(inst, new_inst, bb)

        mark_inst = IRInstruction("assign", [ptr_out], [mark_out])
        self._copy_metadata(inst, mark_inst, bb)
        lowered.append(mark_inst)

        entry = {
            "origin": inst,
            "ptr": ptr_out,
            "mark": mark_out,
            "aligned_var": aligned_var,
            "bump_inst": bump_inst,
            "introduced": tuple(lowered),
        }
        entry["mark_inst"] = mark_inst

        return lowered, entry

    def _copy_metadata(self, source: IRInstruction, target: IRInstruction, bb) -> None:
        target.parent = bb
        target.ast_source = source.ast_source
        target.error_msg = source.error_msg

    def _augment_invoke(self, inst: IRInstruction, fmp_var: IRVariable) -> None:
        # Invoke's internal operand layout (after parser reversal):
        #   operands[0] = target label
        #   operands[1:] = user args in callee-param order
        #   operands[-1] = hidden FMP when present
        # The callee's params bind in internal operand order, so appending
        # the hidden FMP keeps every user-arg position stable and makes the
        # FMP param the last param before return_pc.
        #
        # We intentionally do not thread a new FMP value back out of the
        # callee. The caller's current FMP SSA value survives the invoke
        # via liveness, so any callee allocation left unreleased is
        # reclaimed when control returns to the caller.
        InvokeLayout(self.function.ctx, inst).append_hidden_fmp_operand(fmp_var)

    def _prune_dead_hidden_fmp_param(self, fn) -> bool:
        param_inst = FunctionCallLayout(fn).hidden_fmp_param
        if param_inst is None:
            return False

        dead_chain = self._collect_dead_fmp_chain(param_inst.output)
        if dead_chain is None:
            return False

        for inst in dead_chain:
            inst.parent.remove_instruction(inst)
        fn.entry.remove_instruction(param_inst)
        return True

    def _collect_dead_fmp_chain(self, root: IRVariable) -> list[IRInstruction] | None:
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        dead_insts: list[IRInstruction] = []
        seen_vars: set[IRVariable] = set()
        worklist = [root]

        while len(worklist) > 0:
            var = worklist.pop()
            if var in seen_vars:
                continue
            seen_vars.add(var)

            for use in dfg.get_uses(var):
                if use.opcode not in ("assign", "phi"):
                    return None

                dead_insts.append(use)
                outputs = use.get_outputs()
                assert len(outputs) == 1, use
                worklist.append(outputs[0])

        return dead_insts

    def _deaugment_stale_invoke_fmp_args(self, fn) -> bool:
        changed = False

        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "invoke":
                    continue

                layout = InvokeLayout(fn.ctx, inst)
                callee = layout.callee
                if callee is None:
                    continue
                if callee._has_fmp_param:
                    continue

                expected_arg_count = FunctionCallLayout(callee).expected_user_arg_count
                current_arg_count = layout.actual_operand_count_after_target
                if current_arg_count != expected_arg_count + 1:
                    continue

                layout.remove_trailing_operand()
                changed = True

        return changed
