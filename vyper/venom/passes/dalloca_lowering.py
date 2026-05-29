from typing import ClassVar

from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import (
    BasePtrAnalysis,
    DFGAnalysis,
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
from vyper.venom.call_layout import FunctionCallLayout, InvokeLayout
from vyper.venom.memory_location import Allocation
from vyper.venom.passes.base_pass import IRPass, PassRef

IDENTITY_PRECOMPILE = 4


class DallocaLoweringPass(IRPass):
    """
    Lower `dalloca` into explicit FMP-threaded IR.

    Producer-facing dynamic allocation has one output:

        %ptr = dalloca %size

    `%ptr` is both the allocated pointer and the pre-bump FMP mark. Producers
    do not emit a release instruction. This pass may synthesize conservative
    rewinds for dead LIFO allocation suffixes at points where the current FMP
    is observed by later lowering.

    `dret` is lowered earlier by DretLoweringPass so reclaim decisions can run
    after SSA while raw dynamic-return terminators are still gone before
    inlining.
    """

    required_predecessors: ClassVar[tuple[PassRef, ...]] = ("MakeSSA",)
    required_successors: ClassVar[tuple[PassRef, ...]] = ("MakeSSA",)

    def run_pass(self):
        fn = self.function
        had_fmp = fn._needs_fmp

        has_dalloca, has_dfree, has_dret, calls_needs_fmp = self._scan_function_flags(fn)
        if has_dret:
            raise CompilerPanic("DretLoweringPass must run before DallocaLoweringPass")

        if fn._needs_fmp and not has_dalloca and not has_dfree:
            changed = self._deaugment_stale_invoke_fmp_args(fn)
            if changed:
                self._invalidate_analyses()

            if not calls_needs_fmp:
                if not fn._returns_adopted_fmp and self._prune_dead_hidden_fmp_param(fn):
                    fn._needs_fmp = False
                    self._invalidate_analyses()
                    return

                fn._needs_fmp = True
                return

        if not has_dalloca and not has_dfree and not has_dret and not calls_needs_fmp:
            if not fn._returns_adopted_fmp:
                fn._needs_fmp = False
            return

        hidden_fmp_var = self._ensure_hidden_fmp_param(fn, hidden_may_exist=had_fmp)
        fn._needs_fmp = True
        fmp_var = hidden_fmp_var
        canonicalize_adopted_fmp = False
        if has_dalloca or has_dfree or calls_needs_fmp:
            fmp_var = self._materialize_fmp_thread_var(fn, hidden_fmp_var)
            canonicalize_adopted_fmp = True

        liveness = self.analyses_cache.request_analysis(LivenessAnalysis)
        base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)
        bb_entry_stacks = self._compute_bb_entry_stacks(fn, base_ptrs, liveness)

        for bb in fn.get_basic_blocks():
            self._rewrite_bb(
                bb, fmp_var, canonicalize_adopted_fmp, base_ptrs, liveness, bb_entry_stacks[bb]
            )

        fn._needs_fmp = True

        self._invalidate_analyses()

    def _infer_dret_metadata(self, fn) -> None:
        shapes: set[tuple[int, int]] = set()
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "dret" or len(inst.operands) == 0:
                    continue
                dyn_count_op = inst.operands[0]
                if not isinstance(dyn_count_op, IRLiteral):
                    continue
                dyn_count = dyn_count_op.value
                ordinary_count = len(inst.operands) - 2 - 2 * dyn_count
                if dyn_count >= 1 and ordinary_count >= 0:
                    shapes.add((ordinary_count, dyn_count))

        if len(shapes) == 1:
            fn._dret_shape = next(iter(shapes))
            fn._returns_adopted_fmp = True
            fn._needs_fmp = True

    def _scan_function_flags(self, fn) -> tuple[bool, bool, bool, bool]:
        has_dalloca = False
        has_dfree = False
        has_dret = False
        calls_needs_fmp = False

        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "dalloca":
                    has_dalloca = True
                    continue
                if inst.opcode == "dfree":
                    has_dfree = True
                    continue
                if inst.opcode == "dret":
                    has_dret = True
                    continue
                if inst.opcode == "invoke" and not calls_needs_fmp:
                    callee = InvokeLayout(fn.ctx, inst).callee
                    calls_needs_fmp = callee is not None and callee._needs_fmp

        return has_dalloca, has_dfree, has_dret, calls_needs_fmp

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

    def _ensure_hidden_fmp_param(self, fn, hidden_may_exist: bool = False) -> IRVariable:
        layout = FunctionCallLayout(fn)
        params = layout.params
        return_pc_offset = int(layout.has_return_pc_param)

        if hidden_may_exist:
            hidden_fmp_param = layout.hidden_fmp_param
            if hidden_fmp_param is not None:
                return hidden_fmp_param.output

        if fn._invoke_param_count is not None:
            hidden_pos = fn._invoke_param_count
            hidden_exists = len(params) == fn._invoke_param_count + 1 + return_pc_offset
            if hidden_exists and hidden_pos < len(params):
                return params[hidden_pos].output

        fmp_var = fn.get_next_variable()
        param_inst = IRInstruction("param", [], [fmp_var])
        fn.entry.insert_instruction(param_inst, index=layout.hidden_fmp_param_insert_index)
        return fmp_var

    def _materialize_entry_fmp(self, fn, fmp_var: IRVariable) -> IRVariable:
        entry_fmp_var = fn.get_next_variable()
        inst = IRInstruction("assign", [fmp_var], [entry_fmp_var])

        params = FunctionCallLayout(fn).params
        if len(params) == 0:
            index = 0
        else:
            index = max(fn.entry.instructions.index(param) for param in params) + 1
        fn.entry.insert_instruction(inst, index=index)
        return entry_fmp_var

    def _materialize_fmp_thread_var(self, fn, fmp_var: IRVariable) -> IRVariable:
        thread_fmp_var = fn.get_next_variable()
        inst = IRInstruction("assign", [fmp_var], [thread_fmp_var])

        params = FunctionCallLayout(fn).params
        if len(params) == 0:
            index = 0
        else:
            index = max(fn.entry.instructions.index(param) for param in params) + 1
        fn.entry.insert_instruction(inst, index=index)
        return thread_fmp_var

    def _compute_bb_entry_stacks(
        self, fn, base_ptrs: BasePtrAnalysis, liveness
    ) -> dict[IRBasicBlock, tuple[IRVariable, ...]]:
        bbs = list(fn.get_basic_blocks())
        entry_stacks: dict[IRBasicBlock, tuple[IRVariable, ...]] = {bb: tuple() for bb in bbs}
        exit_stacks: dict[IRBasicBlock, tuple[IRVariable, ...]] = {bb: tuple() for bb in bbs}
        cfg = liveness.cfg

        changed = True
        while changed:
            changed = False
            for bb in bbs:
                in_bbs = list(cfg.cfg_in(bb))
                if len(in_bbs) == 0:
                    new_entry: tuple[IRVariable, ...] = tuple()
                else:
                    new_entry = self._common_stack_prefix([exit_stacks[pred] for pred in in_bbs])

                if entry_stacks[bb] != new_entry:
                    entry_stacks[bb] = new_entry
                    changed = True

                new_exit = self._simulate_bb_stack(bb, list(new_entry), base_ptrs, liveness)
                if exit_stacks[bb] != new_exit:
                    exit_stacks[bb] = new_exit
                    changed = True

        return entry_stacks

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
        self, bb, stack, base_ptrs: BasePtrAnalysis, liveness
    ) -> tuple[IRVariable, ...]:
        for inst in bb.instructions:
            if self._is_reclaim_point(inst):
                suffix_start = self._dead_lifo_suffix_start(
                    stack, base_ptrs, liveness.live_vars_at(inst)
                )
                del stack[suffix_start:]

            if inst.opcode == "dalloca":
                stack.append(inst.output)
            elif inst.opcode == "dfree":
                stack.clear()
            elif inst.opcode == "invoke":
                callee = InvokeLayout(self.function.ctx, inst).callee
                if callee is not None and callee._returns_adopted_fmp:
                    stack.clear()

        return tuple(stack)

    def _is_reclaim_point(self, inst: IRInstruction) -> bool:
        if inst.opcode == "dalloca":
            return True
        if inst.opcode in ("jmp", "jnz", "djmp"):
            return True
        if inst.opcode == "invoke":
            callee = InvokeLayout(self.function.ctx, inst).callee
            return callee is not None and callee._needs_fmp
        return False

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
        for live_var in live_vars:
            for live_ptr in base_ptrs.get_possible_ptrs(live_var):
                if live_ptr.base_alloca == allocation:
                    return True
        return False

    def _rewrite_bb(
        self,
        bb,
        fmp_var,
        canonicalize_adopted_fmp,
        base_ptrs: BasePtrAnalysis,
        liveness,
        entry_stack,
    ) -> None:
        new_instructions: list[IRInstruction] = []
        stack = list(entry_stack)
        current_fmp_var = fmp_var

        for inst in bb.instructions:
            if self._is_reclaim_point(inst):
                reclaimed = self._emit_auto_reclaim(
                    inst, fmp_var, bb, stack, base_ptrs, liveness, new_instructions
                )
                if reclaimed:
                    current_fmp_var = fmp_var

            if inst.opcode == "dalloca":
                lowered = self._lower_dalloca(inst, bb, current_fmp_var, fmp_var)
                stack.append(inst.output)
                new_instructions.extend(lowered)
                current_fmp_var = fmp_var
                continue

            if inst.opcode == "dfree":
                # Legacy low-level restore. Producer-facing code should not
                # emit this, but keeping the lowering makes stale hand-written
                # IR fail safe instead of reaching codegen.
                stack.clear()
                new_instructions.append(self._restore_fmp_inst(inst.operands[0], fmp_var, bb, inst))
                current_fmp_var = fmp_var
                continue

            if inst.opcode == "invoke":
                callee = InvokeLayout(self.function.ctx, inst).callee
                hidden_fmp_output = None
                if callee is not None and callee._needs_fmp:
                    hidden_fmp_output = self._augment_invoke(inst, current_fmp_var)
                new_instructions.append(inst)
                if callee is not None and callee._returns_adopted_fmp:
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
        self, inst, fmp_var, bb, stack, base_ptrs: BasePtrAnalysis, liveness, new_instructions
    ) -> bool:
        suffix_start = self._dead_lifo_suffix_start(stack, base_ptrs, liveness.live_vars_at(inst))
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

    def _lower_dret(
        self, inst: IRInstruction, bb, entry_fmp_var: IRVariable
    ) -> list[IRInstruction]:
        assert len(inst.operands) >= 4, inst
        dyn_count_op = inst.operands[0]
        assert isinstance(dyn_count_op, IRLiteral), inst
        dyn_count = dyn_count_op.value
        assert dyn_count >= 1, inst

        return_pc = inst.operands[-1]
        ordinary_count = len(inst.operands) - 2 - 2 * dyn_count
        assert ordinary_count >= 0, inst
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

        ret_inst = IRInstruction("ret", [*ordinary_returns, *dsts, new_fmp, return_pc], [])
        self._copy_metadata(inst, ret_inst, bb)
        lowered.append(ret_inst)
        return lowered

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
        if not has_hidden_fmp_operand:
            layout.append_hidden_fmp_operand(fmp_var)

        hidden_fmp_output = None
        if callee._returns_adopted_fmp:
            outputs = inst.get_outputs()
            has_hidden_fmp_output = False
            if callee._dret_shape is not None:
                ordinary_count, dynamic_count = callee._dret_shape
                user_output_count = ordinary_count + dynamic_count
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
                and callee._returns_adopted_fmp
                and len(outputs) > 0
                and outputs[-1] == value
            )

        return False

    def _deaugment_stale_invoke_fmp_args(self, fn) -> bool:
        changed = False
        caller_layout = FunctionCallLayout(fn)
        hidden_fmp_param = caller_layout.hidden_fmp_param
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
                if callee._needs_fmp:
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


class DretLoweringPass(DallocaLoweringPass):
    """
    Lower `dret` and hidden adopted-FMP invoke edges before inlining.

    This pass intentionally leaves raw `dalloca` instructions in place. The
    later DallocaLoweringPass runs after SSA and handles allocation reclaim.
    """

    required_predecessors: ClassVar[tuple[PassRef, ...]] = ()
    required_successors: ClassVar[tuple[PassRef, ...]] = ()

    def run_pass(self):
        fn = self.function
        had_fmp = fn._needs_fmp
        self._infer_dret_metadata(fn)

        has_dalloca, has_dfree, has_dret, calls_needs_fmp = self._scan_function_flags(fn)
        del has_dalloca, has_dfree

        if not has_dret and not calls_needs_fmp:
            return

        fmp_var = self._ensure_hidden_fmp_param(fn, hidden_may_exist=had_fmp)
        fn._needs_fmp = True
        entry_fmp_var = fmp_var
        if has_dret:
            entry_fmp_var = self._materialize_entry_fmp(fn, fmp_var)

        for bb in fn.get_basic_blocks():
            self._rewrite_dret_bb(bb, fmp_var, entry_fmp_var)

        if has_dret:
            fn._returns_adopted_fmp = True

        self._invalidate_analyses()

    def _rewrite_dret_bb(self, bb, fmp_var: IRVariable, entry_fmp_var: IRVariable) -> None:
        new_instructions: list[IRInstruction] = []

        for inst in bb.instructions:
            if inst.opcode == "dret":
                new_instructions.extend(self._lower_dret(inst, bb, entry_fmp_var))
                continue

            if inst.opcode == "invoke":
                callee = InvokeLayout(self.function.ctx, inst).callee
                if callee is not None and callee._needs_fmp:
                    self._augment_invoke(inst, fmp_var)

            new_instructions.append(inst)

        bb.instructions = new_instructions
