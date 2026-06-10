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
from vyper.venom.memory_location import Allocation, memory_read_ops, memory_write_ops
from vyper.venom.passes.base_pass import IRPass, PassRef

IDENTITY_PRECOMPILE = 4

# instructions through which BasePtrAnalysis propagates pointer facts; a
# pointer flowing into these stays visible to SSA-based liveness.
_PTR_PROPAGATION_OPS = frozenset(["add", "sub", "assign", "phi", "bump", "dalloca", "alloca"])


class DallocaLoweringPass(IRPass):
    """
    Lower `dalloca` into explicit FMP-threaded IR.

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
    """

    required_predecessors: ClassVar[tuple[PassRef, ...]] = ("MakeSSA",)
    required_successors: ClassVar[tuple[PassRef, ...]] = ("MakeSSA",)

    # whether the FMP value threaded by the current run reflects every
    # allocation in the function. only then may `_augment_invoke` overwrite an
    # existing hidden-FMP operand. False for repeat runs on already-lowered
    # IR (pre-existing `bump`s).
    _fmp_model_authoritative: bool = False

    # allocations whose pointer escapes SSA tracking; never reclaimed.
    # recomputed per run in run_pass.
    _pinned_allocations: frozenset[Allocation] = frozenset()

    def run_pass(self):
        fn = self.function

        self.dynamic_memory = self.analyses_cache.force_analysis(DynamicMemoryAnalysis)
        info = self.dynamic_memory.get_info(fn)
        had_fmp = info.has_physical_hidden_fmp

        has_dalloca = info.has_dalloca
        has_dret = info.has_dret
        has_fmp_ops = info.has_fmp_ops
        calls_needs_fmp = info.calls_need_fmp
        if has_dret:
            raise CompilerPanic("DretDesugarPass must run before DallocaLoweringPass")

        if had_fmp and not has_dalloca and not has_fmp_ops:
            changed = self._deaugment_stale_invoke_fmp_args(fn)
            if changed:
                self._invalidate_analyses()

            if not calls_needs_fmp:
                if not info.returns_adopted_fmp and self._prune_dead_hidden_fmp_param(fn):
                    self._invalidate_analyses()
                    return

                return

        if not has_dalloca and not has_fmp_ops and not calls_needs_fmp:
            return

        # Pre-existing `bump`s mean a previous run already lowered (and
        # threaded) allocations that this run does not model, so the FMP value
        # threaded below would be stale at points past those bumps.
        self._fmp_model_authoritative = not any(
            inst.opcode == "bump" for bb in fn.get_basic_blocks() for inst in bb.instructions
        )

        hidden_fmp_var = self._ensure_hidden_fmp_param(fn, hidden_may_exist=had_fmp)
        fmp_var = hidden_fmp_var
        canonicalize_adopted_fmp = False
        if has_dalloca or has_fmp_ops or calls_needs_fmp:
            fmp_var = self._materialize_fmp_copy(fn, hidden_fmp_var)
            canonicalize_adopted_fmp = True

        liveness = self.analyses_cache.request_analysis(LivenessAnalysis)
        base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self._pinned_allocations = self._compute_escaping_allocations(fn, base_ptrs)
        bb_entry_stacks = self._compute_bb_entry_stacks(fn, base_ptrs, liveness)

        for bb in fn.get_basic_blocks():
            entry_stack, entry_ghosts = bb_entry_stacks[bb]
            self._rewrite_bb(
                bb,
                fmp_var,
                canonicalize_adopted_fmp,
                base_ptrs,
                liveness,
                entry_stack,
                entry_ghosts,
            )

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

    def _ensure_hidden_fmp_param(self, fn, hidden_may_exist: bool = False) -> IRVariable:
        layout = FunctionCallLayout(fn)
        params = layout.params
        return_pc_offset = int(layout.has_return_pc_param)

        if hidden_may_exist:
            hidden_fmp_param = layout.hidden_fmp_param
            if hidden_fmp_param is not None:
                return hidden_fmp_param.output
            if fn is fn.ctx.entry_function:
                entry_params = [inst for inst in fn.entry.instructions if inst.opcode == "param"]
                if len(entry_params) == 1:
                    return entry_params[0].output

        if fn._invoke_param_count is not None:
            hidden_pos = fn._invoke_param_count
            hidden_exists = len(params) == fn._invoke_param_count + 1 + return_pc_offset
            if hidden_exists and hidden_pos < len(params):
                return params[hidden_pos].output

        fmp_var = fn.get_next_variable()
        param_inst = IRInstruction("param", [], [fmp_var])
        fn.entry.insert_instruction(param_inst, index=layout.hidden_fmp_param_insert_index)
        return fmp_var

    def _materialize_fmp_copy(self, fn, fmp_var: IRVariable) -> IRVariable:
        copy_var = fn.get_next_variable()
        inst = IRInstruction("assign", [fmp_var], [copy_var])

        params = FunctionCallLayout(fn).params
        if len(params) == 0:
            index = 0
        else:
            index = max(fn.entry.instructions.index(param) for param in params) + 1
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
        self,
        bb,
        fmp_var,
        canonicalize_adopted_fmp,
        base_ptrs: BasePtrAnalysis,
        liveness,
        entry_stack,
        entry_ghosts,
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
                        if canonicalize_adopted_fmp and hidden_fmp_output != fmp_var:
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

        expected_user_args = FunctionCallLayout(callee).expected_user_arg_count
        has_hidden_fmp_operand = len(inst.operands) == 1 + expected_user_args + 1
        if has_hidden_fmp_operand:
            # The frontend pipeline never reaches this branch anymore:
            # DretDesugarPass touches no invokes, so this pass is the only
            # writer of the hidden operand and the append branch below is the
            # primary path. Hand-written half-lowered IR may still carry a
            # (possibly stale) hidden operand; overwrite it with the current
            # FMP -- set, don't just ensure.
            #
            # Only overwrite when this run's FMP model is authoritative
            # (`_fmp_model_authoritative`): a repeat run on already-lowered IR
            # (pre-existing `bump`s) models the FMP as the raw entry param and
            # would re-stale the operand a previous run threaded correctly.
            if self._fmp_model_authoritative:
                inst.operands[-1] = fmp_var
        else:
            layout.append_hidden_fmp_operand(fmp_var)

        hidden_fmp_output = None
        callee_info = self.dynamic_memory.get_info(callee)
        if callee_info.returns_adopted_fmp:
            outputs = inst.get_outputs()
            has_hidden_fmp_output = False
            if callee_info.user_return_count is not None:
                user_output_count = callee_info.user_return_count
                has_hidden_fmp_output = len(outputs) > user_output_count
                if has_hidden_fmp_output:
                    hidden_fmp_output = outputs[user_output_count]
            elif len(outputs) > 0:
                has_hidden_fmp_output = outputs[-1] == fmp_var
                if has_hidden_fmp_output:
                    hidden_fmp_output = outputs[-1]

            if not has_hidden_fmp_output:
                layout.append_hidden_fmp_output(fmp_var)
                hidden_fmp_output = fmp_var

        return hidden_fmp_output

    def _hidden_fmp_param(self, fn):
        param_inst = FunctionCallLayout(fn).hidden_fmp_param
        if param_inst is not None:
            return param_inst

        if fn is not fn.ctx.entry_function:
            return None

        if not self.dynamic_memory.get_info(fn).has_physical_hidden_fmp:
            return None

        params = [inst for inst in fn.entry.instructions if inst.opcode == "param"]
        if len(params) != 1:
            return None
        return params[0]

    def _prune_dead_hidden_fmp_param(self, fn) -> bool:
        param_inst = self._hidden_fmp_param(fn)
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

    def _is_fmp_value(
        self,
        value: IROperand,
        root: IRVariable,
        dfg: DFGAnalysis,
        seen: set[IRVariable] | None = None,
    ) -> bool:
        if value == root:
            return True
        if not isinstance(value, IRVariable):
            return False

        if seen is None:
            seen = set()
        if value in seen:
            return False
        seen.add(value)

        producer = dfg.get_producing_instruction(value)
        if producer is None:
            return False

        if producer.opcode == "assign" and len(producer.operands) == 1:
            return self._is_fmp_value(producer.operands[0], root, dfg, seen)

        if producer.opcode == "phi":
            return all(
                self._is_fmp_value(op, root, dfg, seen.copy()) for _, op in producer.phi_operands
            )

        if producer.opcode == "bump":
            outputs = producer.get_outputs()
            if len(outputs) == 2 and outputs[1] == value:
                return self._is_fmp_value(producer.operands[0], root, dfg, seen)
            return False

        if producer.opcode == "invoke":
            callee = InvokeLayout(self.function.ctx, producer).callee
            outputs = producer.get_outputs()
            return (
                callee is not None
                and self.dynamic_memory.get_info(callee).returns_adopted_fmp
                and len(outputs) > 0
                and outputs[-1] == value
            )

        return False

    def _deaugment_stale_invoke_fmp_args(self, fn) -> bool:
        changed = False
        hidden_fmp_param = self._hidden_fmp_param(fn)
        if hidden_fmp_param is None:
            return False
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "invoke":
                    continue

                layout = InvokeLayout(fn.ctx, inst)
                callee = layout.callee
                if callee is None:
                    continue
                if self.dynamic_memory.get_info(callee).needs_fmp:
                    continue

                expected_arg_count = FunctionCallLayout(callee).expected_user_arg_count
                current_arg_count = layout.actual_operand_count_after_target
                if current_arg_count != expected_arg_count + 1:
                    continue

                trailing_operand = inst.operands[-1]
                if not self._is_fmp_value(trailing_operand, hidden_fmp_param.output, dfg):
                    continue

                # This invoke still has one extra trailing operand and that
                # operand belongs to the caller's FMP chain, but the callee no
                # longer has a hidden FMP param. Drop the stale hidden arg.
                layout.remove_trailing_operand()
                changed = True

        return changed


class DretDesugarPass(DallocaLoweringPass):
    """
    Desugar `dret` into FMP virtual-register IR before inlining.

    Purely local: a function containing `dret` gets `%e = getfmp` at entry,
    and each `dret` becomes the dst-chain arithmetic rooted at `%e`, the
    pack-by-copy memory copies, `setfmp %new_fmp` (an *advance* over the
    packed data, never a rewind) and a `retfmp` publishing terminator.
    Functions without `dret` are untouched; no params and no invokes are
    modified anywhere -- the calling convention is materialized later by
    DallocaLoweringPass.

    This pass intentionally leaves raw `dalloca` instructions in place. The
    later DallocaLoweringPass runs after SSA and handles allocation reclaim.
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
