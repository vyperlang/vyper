from typing import ClassVar

from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import (
    BasePtrAnalysis,
    DFGAnalysis,
    DynamicMemoryAnalysis,
    LivenessAnalysis,
    LoadAnalysis,
    MemLivenessAnalysis,
    MemoryAliasAnalysis,
    MemSSA,
    ReadonlyMemoryArgsGlobalAnalysis,
    VarDefinition,
    VariableRangeAnalysis,
)
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.call_layout import FunctionCallLayout, InvokeLayout, parse_dret_shape
from vyper.venom.function import FmpSignature
from vyper.venom.memory_location import Allocation, memory_read_ops, memory_write_ops
from vyper.venom.passes.base_pass import IRPass, PassRef

IDENTITY_PRECOMPILE = 4

# instructions through which BasePtrAnalysis propagates pointer facts; a
# pointer flowing into these stays visible to SSA-based liveness.
_PTR_PROPAGATION_OPS = frozenset(["add", "sub", "assign", "phi", "bump", "dalloca", "alloca"])


class FmpLoweringPass(IRPass):
    """
    Lower `dalloca` and the FMP virtual-register opcodes into explicit
    FMP-threaded IR. This pass is the *single owner* of the hidden-FMP
    calling convention: it alone materializes the hidden FMP param
    (`fmp_param`), seeds the entry function's FMP root (`initial_fmp`),
    and writes the hidden invoke operand (assert-and-set, never ensure).

    Producer-facing dynamic allocation has one output:

        %ptr = dalloca %size

    `%ptr` is both the allocated pointer and the pre-bump FMP mark. Producers
    do not emit a release instruction. This pass may synthesize conservative
    rewinds for dead LIFO allocation suffixes at points where the current FMP
    is observed by later lowering.

    `dret` is desugared earlier by DretDesugarPass into the FMP
    virtual-register opcodes (`getfmp`/`setfmp`/`retfmp`), which this pass
    threads against the same FMP runner:
    - `getfmp` reads the current FMP value
    - `setfmp` writes it (and invalidates all tracked reclaim marks)
    - `retfmp` returns values *and* publishes the FMP to the caller; it
      lowers to `ret` with the hidden adopted-FMP value appended

    After lowering, the function's convention shape is frozen as
    `fn._fmp_signature`; FmpPrunePass may later delete a dead hidden FMP
    param and reseal the signature -- before any caller is lowered (the
    callee-first pass driver), so callers only augment against final shapes.
    """

    required_predecessors: ClassVar[tuple[PassRef, ...]] = ("MakeSSA",)
    required_successors: ClassVar[tuple[PassRef, ...]] = ("MakeSSA",)

    # allocations whose pointer escapes SSA tracking; never reclaimed.
    # recomputed per run in run_pass.
    _pinned_allocations: frozenset[Allocation] = frozenset()

    def run_pass(self):
        fn = self.function

        self.dynamic_memory = self.analyses_cache.force_analysis(DynamicMemoryAnalysis)
        info = self.dynamic_memory.get_info(fn)

        if info.has_dret:
            raise CompilerPanic("DretDesugarPass must run before FmpLoweringPass")

        if info.is_lowered:
            # hand-written already-lowered input: the convention has been
            # materialized externally; freeze the observed shape and leave
            # the IR untouched. (Stage 4 replaces this inference with an
            # explicit function-header annotation.)
            if fn._fmp_signature is None:
                fn._fmp_signature = FmpSignature(
                    has_fmp_param=info.has_physical_hidden_fmp, publishes=info.returns_adopted_fmp
                )
            return

        if fn._fmp_signature is not None:
            raise CompilerPanic(f"FmpLoweringPass ran twice on {fn.name}")

        if not (info.has_dalloca or info.has_fmp_ops or info.calls_need_fmp):
            # leaf fast path: no FMP needs, zero plumbing
            fn._fmp_signature = FmpSignature(has_fmp_param=False, publishes=False)
            return

        # `retfmp` (the desugared publishing terminator) is the publish fact
        publishes = info.returns_adopted_fmp

        fmp_root_var, has_fmp_param = self._materialize_fmp_root(fn)
        fmp_var = self._materialize_fmp_copy(fn, fmp_root_var)

        liveness = self.analyses_cache.request_analysis(LivenessAnalysis)
        base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self._pinned_allocations = self._compute_escaping_allocations(fn, base_ptrs)
        bb_entry_stacks = self._compute_bb_entry_stacks(fn, base_ptrs, liveness)

        for bb in fn.get_basic_blocks():
            entry_stack, entry_ghosts = bb_entry_stacks[bb]
            self._rewrite_bb(bb, fmp_var, base_ptrs, liveness, entry_stack, entry_ghosts)

        # freeze the convention shape; FmpPrunePass may reseal it
        fn._fmp_signature = FmpSignature(has_fmp_param=has_fmp_param, publishes=publishes)

        self._invalidate_analyses()

    def _invalidate_analyses(self) -> None:
        self.analyses_cache.invalidate_analysis(LoadAnalysis)
        self.analyses_cache.invalidate_analysis(MemSSA)
        self.analyses_cache.invalidate_analysis(MemoryAliasAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)
        self.analyses_cache.invalidate_analysis(MemLivenessAnalysis)
        self.analyses_cache.invalidate_analysis(VarDefinition)
        self.analyses_cache.invalidate_analysis(VariableRangeAnalysis)
        self.analyses_cache.invalidate_analysis(ReadonlyMemoryArgsGlobalAnalysis)
        self.analyses_cache.invalidate_analysis(DynamicMemoryAnalysis)

    def _materialize_fmp_root(self, fn) -> tuple[IRVariable, bool]:
        """
        Materialize the function's FMP root and return `(root_var,
        has_fmp_param)`. The entry function's root is an explicit
        `initial_fmp` instruction (lowered to the deferred assembler CONST);
        every other FMP-needing function receives a hidden `fmp_param`,
        physically placed after the user params and before the return-PC
        param. The return-PC param, when discoverable, is normalized to its
        dedicated `retpc_param` opcode (same stack slot, only the name
        changes).
        """
        fmp_var = fn.get_next_variable()

        if fn is fn.ctx.entry_function:
            inst = IRInstruction("initial_fmp", [], [fmp_var])
            fn.entry.insert_instruction(inst, index=self._after_params_index(fn))
            return fmp_var, False

        layout = FunctionCallLayout(fn)
        return_pc_param = layout.return_pc_param
        if return_pc_param is None:
            # every invoked function physically receives the return PC as
            # the top-of-stack entry slot. When it is not discoverable (no
            # `ret` to anchor it and no metadata -- e.g. a metadata-less
            # never-returning forwarder), the last plain param names that
            # slot; with no params at all, synthesize the name so the
            # hidden FMP param can be placed beneath it.
            params = layout.params
            if len(params) > 0:
                return_pc_param = params[-1]
            else:
                return_pc_param = IRInstruction("retpc_param", [], [fn.get_next_variable()])
                fn.entry.insert_instruction(return_pc_param, index=0)
        return_pc_param.opcode = "retpc_param"

        param_inst = IRInstruction("fmp_param", [], [fmp_var])
        fn.entry.insert_instruction(param_inst, index=layout.hidden_fmp_param_insert_index)
        return fmp_var, True

    def _after_params_index(self, fn) -> int:
        params = FunctionCallLayout(fn).params
        if len(params) == 0:
            return 0
        return max(fn.entry.instructions.index(param) for param in params) + 1

    def _materialize_fmp_copy(self, fn, fmp_var: IRVariable) -> IRVariable:
        copy_var = fn.get_next_variable()
        inst = IRInstruction("assign", [fmp_var], [copy_var])

        # insert after the params and after the FMP root definition
        index = self._after_params_index(fn)
        for idx, entry_inst in enumerate(fn.entry.instructions):
            if fmp_var in entry_inst.get_outputs():
                index = max(index, idx + 1)
                break
        fn.entry.insert_instruction(inst, index=index)
        return copy_var

    def _compute_bb_entry_stacks(
        self, fn, base_ptrs: BasePtrAnalysis, liveness
    ) -> dict[IRBasicBlock, tuple[tuple[IRVariable, ...], frozenset[IRVariable]]]:
        """
        Compute, for every basic block, the LIFO allocation stack at entry and
        the set of "ghost" allocations.

        At CFG merges the stack meet is the common prefix of the predecessor
        exit stacks. Allocations dropped from the top by the meet are not
        forgotten: they become *ghosts*. A ghost's mark is lost, but its
        memory may still be live (e.g. carried through a phi), so rewinding
        the FMP to any surviving mark could free it. While any ghost is
        possibly live, reclaim is suppressed entirely (see
        `_reclaim_suffix_start`). Ghosts propagate transitively: once a ghost,
        always a ghost in all successors.

        Termination: ghost sets only grow (unions over predecessors) and are
        bounded by the number of dalloca outputs, so they change finitely
        often. For a fixed ghost assignment, exit stacks are a deterministic
        function of entry stacks, entry stacks are common prefixes of
        predecessor exit stacks, and stack contents are drawn from the finite
        set of dalloca outputs with per-path-bounded height, so the stack
        iteration reaches its fixpoint as before. Hence the combined fixpoint
        terminates.
        """
        bbs = list(fn.get_basic_blocks())
        entry_stacks: dict[IRBasicBlock, tuple[IRVariable, ...]] = {bb: tuple() for bb in bbs}
        exit_stacks: dict[IRBasicBlock, tuple[IRVariable, ...]] = {bb: tuple() for bb in bbs}
        # ghosts are created only at entry meets; blocks don't add ghosts
        # mid-block, so a block's exit ghosts equal its entry ghosts.
        entry_ghosts: dict[IRBasicBlock, frozenset[IRVariable]] = {bb: frozenset() for bb in bbs}
        cfg = liveness.cfg

        changed = True
        while changed:
            changed = False
            for bb in bbs:
                in_bbs = list(cfg.cfg_in(bb))
                if len(in_bbs) == 0:
                    new_entry: tuple[IRVariable, ...] = tuple()
                    new_ghosts = entry_ghosts[bb]
                else:
                    new_entry = self._common_stack_prefix([exit_stacks[pred] for pred in in_bbs])
                    ghosts = set(entry_ghosts[bb])
                    for pred in in_bbs:
                        ghosts.update(entry_ghosts[pred])
                        # allocations dropped from this predecessor by the meet
                        ghosts.update(exit_stacks[pred][len(new_entry) :])
                    new_ghosts = frozenset(ghosts)

                if entry_stacks[bb] != new_entry:
                    entry_stacks[bb] = new_entry
                    changed = True

                if entry_ghosts[bb] != new_ghosts:
                    entry_ghosts[bb] = new_ghosts
                    changed = True

                new_exit = self._simulate_bb_stack(
                    bb, list(new_entry), new_ghosts, base_ptrs, liveness
                )
                if exit_stacks[bb] != new_exit:
                    exit_stacks[bb] = new_exit
                    changed = True

        return {bb: (entry_stacks[bb], entry_ghosts[bb]) for bb in bbs}

    def _common_stack_prefix(self, stacks: list[tuple[IRVariable, ...]]) -> tuple[IRVariable, ...]:
        if len(stacks) == 0:
            return tuple()

        prefix: list[IRVariable] = []
        for values in zip(*stacks, strict=False):
            first = values[0]
            if all(value == first for value in values):
                prefix.append(first)
                continue
            break
        return tuple(prefix)

    def _simulate_bb_stack(
        self, bb, stack, ghosts, base_ptrs: BasePtrAnalysis, liveness
    ) -> tuple[IRVariable, ...]:
        for inst in bb.instructions:
            if self._is_reclaim_point(inst):
                suffix_start = self._reclaim_suffix_start(
                    stack, ghosts, base_ptrs, liveness.live_vars_at(inst)
                )
                del stack[suffix_start:]

            if inst.opcode == "dalloca":
                stack.append(inst.output)
            elif inst.opcode == "setfmp":
                # an explicit FMP write invalidates every tracked mark, like
                # an invoke whose callee adopts the FMP
                stack.clear()
            elif inst.opcode == "invoke":
                callee = InvokeLayout(self.function.ctx, inst).callee
                if callee is not None and self.dynamic_memory.get_info(callee).returns_adopted_fmp:
                    stack.clear()

        return tuple(stack)

    def _is_reclaim_point(self, inst: IRInstruction) -> bool:
        if inst.opcode == "dalloca":
            return True
        if inst.opcode in ("jmp", "jnz", "djmp"):
            return True
        if inst.opcode == "invoke":
            callee = InvokeLayout(self.function.ctx, inst).callee
            return callee is not None and self.dynamic_memory.get_info(callee).needs_fmp
        return False

    def _reclaim_suffix_start(self, stack, ghosts, base_ptrs: BasePtrAnalysis, live_vars) -> int:
        # If any ghost allocation (mark dropped at a CFG meet) is possibly
        # live here, suppress reclaim entirely: rewinding the FMP to a
        # surviving mark could free the ghost's memory. Unknown == live.
        for ghost in ghosts:
            allocation = self._dalloca_allocation(base_ptrs, ghost)
            if allocation is None:
                return len(stack)
            if self._allocation_is_live(base_ptrs, allocation, live_vars):
                return len(stack)
        return self._dead_lifo_suffix_start(stack, base_ptrs, live_vars)

    def _dead_lifo_suffix_start(self, stack, base_ptrs: BasePtrAnalysis, live_vars) -> int:
        suffix_start = len(stack)
        while suffix_start > 0:
            ptr = stack[suffix_start - 1]
            allocation = self._dalloca_allocation(base_ptrs, ptr)
            if allocation is None:
                break
            if self._allocation_is_live(base_ptrs, allocation, live_vars):
                break
            suffix_start -= 1
        return suffix_start

    def _dalloca_allocation(self, base_ptrs: BasePtrAnalysis, ptr: IRVariable) -> Allocation | None:
        possible_ptrs = base_ptrs.get_possible_ptrs(ptr)
        if len(possible_ptrs) != 1:
            return None

        allocation = next(iter(possible_ptrs)).base_alloca
        if allocation.inst.opcode != "dalloca":
            return None
        return allocation

    def _allocation_is_live(
        self, base_ptrs: BasePtrAnalysis, allocation: Allocation, live_vars
    ) -> bool:
        # pinned allocations escaped SSA tracking (e.g. pointer stored to
        # memory as a value); their memory may be reachable even when no SSA
        # alias is live, so treat them as always live.
        if allocation in self._pinned_allocations:
            return True
        for live_var in live_vars:
            for live_ptr in base_ptrs.get_possible_ptrs(live_var):
                if live_ptr.base_alloca == allocation:
                    return True
        return False

    def _compute_escaping_allocations(
        self, fn, base_ptrs: BasePtrAnalysis
    ) -> frozenset[Allocation]:
        """
        Conservatively compute the dynamic allocations whose pointer escapes
        SSA tracking. An operand escapes when it is used outside
        BasePtrAnalysis's propagation grammar (add/sub/assign/phi/bump/
        dalloca/alloca) and outside the address/length positions of known
        memory ops -- e.g. as the stored *value* of a store-family
        instruction, or as an operand of `invoke`/`ret`/`retfmp`/`setfmp`.
        An escaped pointer can re-enter through memory where SSA liveness
        cannot see it, so the allocation must never be reclaimed. Fail
        closed: anything not provably a non-escaping use pins the allocation.
        """
        pinned: set[Allocation] = set()
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode in _PTR_PROPAGATION_OPS:
                    continue

                # operand values consumed by known-safe (address/length)
                # positions, derived from the shared memory-op descriptions.
                safe: list[IROperand] = []
                for access_ops in (memory_read_ops(inst), memory_write_ops(inst)):
                    for op in (access_ops.ofst, access_ops.size):
                        if op is not None:
                            safe.append(op)
                    # post_init aliases max_size to size; only count a
                    # distinct max_size to avoid inflating safe occurrences.
                    max_size = access_ops.max_size
                    if max_size is not None and max_size is not access_ops.size:
                        safe.append(max_size)

                operands = [op for op in inst.operands if isinstance(op, IRVariable)]
                for op in operands:
                    # an operand escapes if it occurs more often than safe
                    # positions account for (`mstore %x, %x` stores the
                    # pointer value at its own address).
                    if operands.count(op) <= safe.count(op):
                        continue
                    for ptr in base_ptrs.get_possible_ptrs(op):
                        if ptr.base_alloca.inst.opcode == "dalloca":
                            pinned.add(ptr.base_alloca)

        return frozenset(pinned)

    def _rewrite_bb(
        self, bb, fmp_var, base_ptrs: BasePtrAnalysis, liveness, entry_stack, entry_ghosts
    ) -> None:
        new_instructions: list[IRInstruction] = []
        stack = list(entry_stack)
        current_fmp_var = fmp_var

        for inst in bb.instructions:
            if self._is_reclaim_point(inst):
                reclaimed = self._emit_auto_reclaim(
                    inst, fmp_var, bb, stack, entry_ghosts, base_ptrs, liveness, new_instructions
                )
                if reclaimed:
                    current_fmp_var = fmp_var

            if inst.opcode == "dalloca":
                lowered = self._lower_dalloca(inst, bb, current_fmp_var, fmp_var)
                stack.append(inst.output)
                new_instructions.extend(lowered)
                current_fmp_var = fmp_var
                continue

            if inst.opcode == "getfmp":
                # read of the FMP virtual register: the current FMP value
                inst.opcode = "assign"
                inst.operands = [current_fmp_var]
                new_instructions.append(inst)
                continue

            if inst.opcode == "setfmp":
                # write of the FMP virtual register: assign into the runner
                # (multiply-assigned; MakeSSA repairs). The write invalidates
                # every tracked reclaim mark, mirroring adopted-FMP invokes.
                inst.opcode = "assign"
                inst.set_outputs([fmp_var])
                new_instructions.append(inst)
                stack.clear()
                current_fmp_var = fmp_var
                continue

            if inst.opcode == "retfmp":
                # publishing return: plain `ret` of the values plus the
                # hidden adopted-FMP value (before the return PC)
                return_pc = inst.operands[-1]
                inst.opcode = "ret"
                inst.operands = [*inst.operands[:-1], current_fmp_var, return_pc]
                new_instructions.append(inst)
                continue

            if inst.opcode == "invoke":
                callee = InvokeLayout(self.function.ctx, inst).callee
                hidden_fmp_output = None
                callee_info = self.dynamic_memory.get_info(callee) if callee is not None else None
                if callee_info is not None and callee_info.needs_fmp:
                    hidden_fmp_output = self._augment_invoke(inst, current_fmp_var)
                new_instructions.append(inst)
                if callee_info is not None and callee_info.returns_adopted_fmp:
                    stack.clear()
                    if hidden_fmp_output is not None:
                        current_fmp_var = hidden_fmp_output
                        if hidden_fmp_output != fmp_var:
                            new_instructions.append(
                                self._restore_fmp_inst(hidden_fmp_output, fmp_var, bb, inst)
                            )
                            current_fmp_var = fmp_var
                continue

            new_instructions.append(inst)

        bb.instructions = new_instructions

    def _emit_auto_reclaim(
        self,
        inst,
        fmp_var,
        bb,
        stack,
        ghosts,
        base_ptrs: BasePtrAnalysis,
        liveness,
        new_instructions,
    ) -> bool:
        suffix_start = self._reclaim_suffix_start(
            stack, ghosts, base_ptrs, liveness.live_vars_at(inst)
        )
        if suffix_start == len(stack):
            return False

        mark = stack[suffix_start]
        del stack[suffix_start:]
        new_instructions.append(self._restore_fmp_inst(mark, fmp_var, bb, inst))
        return True

    def _restore_fmp_inst(
        self, mark: IROperand, fmp_var: IRVariable, bb, origin: IRInstruction
    ) -> IRInstruction:
        inst = IRInstruction("assign", [mark], [fmp_var])
        self._copy_metadata(origin, inst, bb)
        return inst

    def _ceil32_insts(self, size: IROperand, bb, origin: IRInstruction) -> tuple[list, IRVariable]:
        fn = self.function
        a_var = fn.get_next_variable()
        mask_var = fn.get_next_variable()
        aligned_var = fn.get_next_variable()

        add_inst = IRInstruction("add", [IRLiteral(31), size], [a_var])
        mask_inst = IRInstruction("not", [IRLiteral(31)], [mask_var])
        and_inst = IRInstruction("and", [mask_var, a_var], [aligned_var])
        insts = [add_inst, mask_inst, and_inst]
        for new_inst in insts:
            self._copy_metadata(origin, new_inst, bb)
        return insts, aligned_var

    def _lower_dalloca(
        self, inst: IRInstruction, bb, current_fmp_var: IRVariable, fmp_var: IRVariable
    ) -> list[IRInstruction]:
        assert len(inst.operands) == 1, inst
        assert inst.num_outputs == 1, inst

        size = inst.operands[0]
        ptr_out = inst.output

        ceil_insts, aligned_var = self._ceil32_insts(size, bb, inst)
        bump_inst = IRInstruction("bump", [current_fmp_var, aligned_var], [ptr_out, fmp_var])
        self._copy_metadata(inst, bump_inst, bb)
        return [*ceil_insts, bump_inst]

    def _copy_memory(
        self, dst: IROperand, src: IROperand, size: IROperand, bb, origin: IRInstruction
    ) -> list[IRInstruction]:
        if version_check(begin="cancun"):
            inst = IRInstruction("mcopy", [size, src, dst], [])
            self._copy_metadata(origin, inst, bb)
            return [inst]

        gas = self.function.get_next_variable()
        success = self.function.get_next_variable()
        gas_inst = IRInstruction("gas", [], [gas])
        call_inst = IRInstruction(
            "staticcall", [size, dst, size, src, IRLiteral(IDENTITY_PRECOMPILE), gas], [success]
        )
        assert_inst = IRInstruction("assert", [success], [])
        for new_inst in (gas_inst, call_inst, assert_inst):
            self._copy_metadata(origin, new_inst, bb)
        return [gas_inst, call_inst, assert_inst]

    def _copy_metadata(self, source: IRInstruction, target: IRInstruction, bb) -> None:
        target.parent = bb
        target.ast_source = source.ast_source
        target.error_msg = source.error_msg

    def _augment_invoke(self, inst: IRInstruction, fmp_var: IRVariable) -> IRVariable | None:
        layout = InvokeLayout(self.function.ctx, inst)
        callee = layout.callee
        assert callee is not None

        # Assert-and-set: this pass is the *only* writer of the hidden FMP
        # operand, so the operand must not already be present. The input
        # validator rejects half-lowered IR (an invoke already carrying a
        # hidden operand in a function this pass will thread), so this panic
        # is unreachable from validated input.
        expected_user_args = FunctionCallLayout(callee).expected_user_arg_count
        if len(inst.operands) != 1 + expected_user_args:
            raise CompilerPanic(
                f"invoke of {callee.name} already carries a hidden FMP operand "
                f"(mixed raw/lowered IR?): {inst}"
            )
        layout.append_hidden_fmp_operand(fmp_var)

        hidden_fmp_output = None
        callee_info = self.dynamic_memory.get_info(callee)
        if callee_info.returns_adopted_fmp:
            layout.append_hidden_fmp_output(fmp_var)
            hidden_fmp_output = fmp_var

        return hidden_fmp_output


class FmpPrunePass(IRPass):
    """
    Deletion-only second FMP pass (the run-2 slot in the optimization
    pipelines). If the optimization tail removed every use of the hidden FMP
    param materialized by FmpLoweringPass (no `bump`, no publish, no
    FMP-needing invoke survived -- equivalently, the param's transitive use
    chain is pure assign/phi), delete the param together with its dead chain
    and *seal* the function's `fmp_signature`.

    The callee-first pass driver guarantees a callee's signature is sealed
    before any caller is lowered, so callers only ever augment invokes
    against final shapes and no de-augmentation machinery is needed.
    """

    required_predecessors: ClassVar[tuple[PassRef, ...]] = ("FmpLoweringPass",)

    def run_pass(self):
        fn = self.function

        sig = fn._fmp_signature
        if sig is None:
            raise CompilerPanic(f"FmpPrunePass requires FmpLoweringPass ({fn.name})")

        if not sig.has_fmp_param or sig.publishes:
            return

        # only the syntactic fmp_param is pruned; hand-written lowered input
        # without the dedicated opcode keeps its shape as-is
        param_inst = FunctionCallLayout(fn).fmp_param_opcode_inst
        if param_inst is None:
            return

        dead_chain = self._collect_dead_fmp_chain(param_inst.output)
        if dead_chain is None:
            return

        for inst in dead_chain:
            inst.parent.remove_instruction(inst)
        fn.entry.remove_instruction(param_inst)

        # seal the final shape (before any caller lowers)
        fn._fmp_signature = FmpSignature(has_fmp_param=False, publishes=False)

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(VarDefinition)
        self.analyses_cache.invalidate_analysis(DynamicMemoryAnalysis)

    def _collect_dead_fmp_chain(self, root: IRVariable) -> list[IRInstruction] | None:
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        dead_insts: list[IRInstruction] = []
        seen_insts: set[IRInstruction] = set()
        worklist = [root]

        while len(worklist) > 0:
            var = worklist.pop()
            for use in dfg.get_uses(var):
                if use.opcode not in ("assign", "phi"):
                    return None

                if use in seen_insts:
                    continue
                seen_insts.add(use)
                dead_insts.append(use)
                outputs = use.get_outputs()
                assert len(outputs) == 1, use
                worklist.append(outputs[0])

        return dead_insts


class DretDesugarPass(FmpLoweringPass):
    """
    Desugar `dret` into FMP virtual-register IR before inlining.

    Purely local: a function containing `dret` gets `%e = getfmp` at entry,
    and each `dret` becomes the dst-chain arithmetic rooted at `%e`, the
    pack-by-copy memory copies, `setfmp %new_fmp` (an *advance* over the
    packed data, never a rewind) and a `retfmp` publishing terminator.
    Functions without `dret` are untouched; no params and no invokes are
    modified anywhere -- the calling convention is materialized later by
    FmpLoweringPass.

    This pass intentionally leaves raw `dalloca` instructions in place. The
    later FmpLoweringPass runs after SSA and handles allocation reclaim.
    """

    required_predecessors: ClassVar[tuple[PassRef, ...]] = ()
    required_successors: ClassVar[tuple[PassRef, ...]] = ()

    def run_pass(self):
        fn = self.function

        has_dret = any(
            inst.opcode == "dret" for bb in fn.get_basic_blocks() for inst in bb.instructions
        )
        if not has_dret:
            return

        entry_fmp_var = self._insert_entry_getfmp(fn)

        for bb in fn.get_basic_blocks():
            self._desugar_bb(bb, entry_fmp_var)

        self._invalidate_analyses()

    def _insert_entry_getfmp(self, fn) -> IRVariable:
        fmp_var = fn.get_next_variable()
        inst = IRInstruction("getfmp", [], [fmp_var])

        params = FunctionCallLayout(fn).params
        if len(params) == 0:
            index = 0
        else:
            index = max(fn.entry.instructions.index(param) for param in params) + 1
        fn.entry.insert_instruction(inst, index=index)
        return fmp_var

    def _desugar_bb(self, bb, entry_fmp_var: IRVariable) -> None:
        new_instructions: list[IRInstruction] = []

        for inst in bb.instructions:
            if inst.opcode == "dret":
                new_instructions.extend(self._desugar_dret(inst, bb, entry_fmp_var))
                continue

            new_instructions.append(inst)

        bb.instructions = new_instructions

    def _desugar_dret(
        self, inst: IRInstruction, bb, entry_fmp_var: IRVariable
    ) -> list[IRInstruction]:
        shape = parse_dret_shape(inst)
        assert shape is not None, inst
        ordinary_count, _ = shape

        return_pc = inst.operands[-1]
        ordinary_returns = list(inst.operands[1 : 1 + ordinary_count])
        pair_ops = inst.operands[1 + ordinary_count : -1]
        pairs = [(pair_ops[i], pair_ops[i + 1]) for i in range(0, len(pair_ops), 2)]

        lowered: list[IRInstruction] = []
        dsts: list[IRVariable] = []
        prev_dst: IROperand = entry_fmp_var
        prev_aligned: IRVariable | None = None

        for idx, (_, size) in enumerate(pairs):
            if idx == 0:
                dst = entry_fmp_var
            else:
                assert prev_aligned is not None
                dst = self.function.get_next_variable()
                dst_inst = IRInstruction("add", [prev_aligned, prev_dst], [dst])
                self._copy_metadata(inst, dst_inst, bb)
                lowered.append(dst_inst)

            ceil_insts, aligned = self._ceil32_insts(size, bb, inst)
            lowered.extend(ceil_insts)
            dsts.append(dst)
            prev_dst = dst
            prev_aligned = aligned

        assert prev_aligned is not None
        new_fmp = self.function.get_next_variable()
        new_fmp_inst = IRInstruction("add", [prev_aligned, prev_dst], [new_fmp])
        self._copy_metadata(inst, new_fmp_inst, bb)
        lowered.append(new_fmp_inst)

        for dst_op, (src, size) in zip(dsts, pairs, strict=True):
            lowered.extend(self._copy_memory(dst_op, src, size, bb, inst))

        setfmp_inst = IRInstruction("setfmp", [new_fmp], [])
        self._copy_metadata(inst, setfmp_inst, bb)
        lowered.append(setfmp_inst)

        retfmp_inst = IRInstruction("retfmp", [*ordinary_returns, *dsts, return_pc], [])
        self._copy_metadata(inst, retfmp_inst, bb)
        lowered.append(retfmp_inst)
        return lowered
