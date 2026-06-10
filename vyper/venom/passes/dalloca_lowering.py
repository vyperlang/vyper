from dataclasses import dataclass, field
from typing import ClassVar

from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import (
    BasePtrAnalysis,
    DFGAnalysis,
    DominatorTreeAnalysis,
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


@dataclass
class _ReclaimState:
    """
    Abstract reclaim state at a program point.

    `stack` is the tracked LIFO allocation stack: `dalloca` output variables
    in allocation order (bottom -> top). Each mark names the pre-bump FMP of
    its allocation, so along any execution the marks' runtime values are
    non-decreasing bottom -> top and a restore `FMP := mark` frees exactly
    `[mark, FMP)` -- the mark's own region plus everything tracked above it.

    `captures` is the set of in-scope `getfmp` outputs. A capture observes
    the FMP without advancing it, and pointers derived from it may address
    memory arbitrarily far *above* the capture point (the desugared-dret
    pack destinations are the canonical example), so captures are not stack
    entries: while a capture is possibly live it vetoes every restore (see
    FmpLoweringPass._pop_dead_suffix).

    `can_reclaim` is cleared for unreachable blocks during the rewrite walk:
    they still get lowered, but no restores are synthesized there (the
    dominator tree does not cover them, and they cannot execute anyway).
    """

    stack: list[IRVariable] = field(default_factory=list)
    captures: set[IRVariable] = field(default_factory=set)
    can_reclaim: bool = True

    def copy(self) -> "_ReclaimState":
        return _ReclaimState(list(self.stack), set(self.captures), self.can_reclaim)

    def clear(self) -> None:
        self.stack.clear()
        self.captures.clear()

    def frozen(self) -> tuple:
        return (tuple(self.stack), frozenset(self.captures))


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

    # per-run reclaim engine context, (re)computed in run_pass
    fmp_var: IRVariable
    liveness: LivenessAnalysis
    base_ptrs: BasePtrAnalysis
    dom: DominatorTreeAnalysis
    # allocations whose pointer escapes SSA tracking; never reclaimed
    _pinned_allocations: frozenset[Allocation] = frozenset()
    # getfmp capture -> SSA variables (transitively) derived from it
    _capture_derived: dict[IRVariable, set[IRVariable]]
    # getfmp captures whose derived pointers escape SSA tracking
    _pinned_captures: frozenset[IRVariable]
    # dalloca output -> defining basic block (for the restore-dominance check)
    _mark_def_bbs: dict[IRVariable, IRBasicBlock]

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
        self.fmp_var = self._materialize_fmp_copy(fn, fmp_root_var)

        self.liveness = self.analyses_cache.request_analysis(LivenessAnalysis)
        self.base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self._pinned_allocations = self._compute_escaping_allocations(fn, self.base_ptrs)
        self._capture_derived, self._pinned_captures = self._compute_capture_facts(fn)
        self._mark_def_bbs = {
            inst.output: bb
            for bb in fn.get_basic_blocks()
            for inst in bb.instructions
            if inst.opcode == "dalloca"
        }

        entry_states = self._compute_entry_states(fn)

        for bb in fn.get_basic_blocks():
            state = entry_states.get(bb)
            if state is None:
                # unreachable block: lower it (no raw opcode may survive),
                # but never synthesize restores in it
                state = _ReclaimState(can_reclaim=False)
            else:
                state = state.copy()
            new_instructions: list[IRInstruction] = []
            for inst in bb.instructions:
                self._step(state, inst, new_instructions)
            bb.instructions = new_instructions

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

    def _compute_entry_states(self, fn) -> dict[IRBasicBlock, _ReclaimState]:
        """
        Forward dataflow fixpoint computing the reclaim state at every
        reachable basic block entry.

        Lattice and meet. The stack component is ordered by the top-segment
        relation: s' <= s iff s' is a (possibly empty) top segment (suffix)
        of s, with "not yet computed" as top. The meet at a CFG join is the
        LONGEST COMMON TOP SEGMENT of the predecessor exit stacks: a mark
        survives only if every predecessor agrees on it *and on everything
        above it*. Marks dropped by the meet become untracked and are simply
        never reclaimed (sound: leak-until-ret is the default). The capture
        component meets by union (any predecessor's live capture must veto).

        Soundness invariant. Along every execution reaching a point, the
        tracked marks' runtime values are non-decreasing bottom -> top
        (pushes happen at the current FMP; pops restore to a tracked mark;
        setfmp clears the stack), and every untracked-but-possibly-live
        allocation lies entirely below the runtime value of every tracked
        mark. The meet preserves this: a dropped mark sits *below* the
        surviving segment on every predecessor stack (the segment is a
        common suffix), hence below every survivor's value; and marks pushed
        after a clear (setfmp / adopted-FMP invoke) sit at-or-above the
        post-clear FMP, which is above everything previously tracked or
        captured. A restore `FMP := m` therefore frees only `[m, FMP)`:
        the popped marks above `m` (each proven dead and unpinned), and
        `m`'s own dead region -- never an untracked allocation. Note this is
        the inverse of a common-*prefix* meet, which keeps the bottom and is
        unsound: there the dropped remainder sits *above* the survivors, so
        restoring a survivor frees possibly-live divergent allocations.
        getfmp captures are the one upward-unbounded exception and are
        handled by the veto in `_pop_dead_suffix` (never dropped at meets --
        unioned -- and cleared only by setfmp / adopted-FMP invokes, after
        which all future marks sit above the capture-reachable region).

        Termination. The capture sets evolve independently of the stacks
        (transfer: union locals, or reset at clears) and grow monotonically
        under the union meet into a finite powerset, so they converge first.
        For a fixed capture assignment the pop decisions depend only on the
        stack top and static facts (liveness, pins), so the transfer maps a
        top segment of a stack to a top segment of its image; with top-
        initialized re-iteration (in RPO, every block has an already-visited
        predecessor on the first sweep), once a block's entry first becomes
        a finite stack, subsequent meets only shorten or keep it. Stack
        heights are bounded by the dalloca count, so the descending chains
        are finite and the combined fixpoint terminates at the maximum
        (most-precise sound) fixpoint.
        """
        cfg = self.liveness.cfg
        rpo = list(cfg.dfs_post_walk)
        rpo.reverse()

        entry_states: dict[IRBasicBlock, _ReclaimState] = {}
        exit_states: dict[IRBasicBlock, _ReclaimState] = {}

        changed = True
        while changed:
            changed = False
            for bb in rpo:
                # unreachable predecessors never get an exit state and are
                # ignored (they contribute no executions); so are not-yet-
                # visited back-edge predecessors (top-initialization)
                pred_states = [exit_states[pred] for pred in cfg.cfg_in(bb) if pred in exit_states]
                if bb is fn.entry:
                    # function boundary: empty state (met with any back
                    # edges into the entry block)
                    pred_states.append(_ReclaimState())
                assert len(pred_states) > 0  # RPO: a predecessor was visited
                entry = self._meet(pred_states)
                entry_states[bb] = entry

                state = entry.copy()
                for inst in bb.instructions:
                    self._step(state, inst, None)

                old = exit_states.get(bb)
                if old is None or old.frozen() != state.frozen():
                    exit_states[bb] = state
                    changed = True

        return entry_states

    def _meet(self, states: list[_ReclaimState]) -> _ReclaimState:
        stacks = [state.stack for state in states]
        depth = min(len(stack) for stack in stacks)

        common = 0
        while common < depth:
            mark = stacks[0][-(common + 1)]
            if any(stack[-(common + 1)] != mark for stack in stacks[1:]):
                break
            common += 1

        stack = stacks[0][len(stacks[0]) - common :] if common > 0 else []
        captures: set[IRVariable] = set()
        for state in states:
            captures.update(state.captures)
        return _ReclaimState(stack=list(stack), captures=captures)

    def _step(self, state: _ReclaimState, inst: IRInstruction, out: list | None) -> None:
        """
        The single transfer/rewrite interpreter, shared by the dataflow
        fixpoint (`out is None`: state transition only) and the rewrite walk
        (`out` collects the lowered instructions). One interpreter guarantees
        the rewrite-time state is exactly the fixpoint's transfer -- the old
        engine's two hand-synchronized walkers were themselves a bug source.
        """
        if self._is_reclaim_point(inst):
            mark = self._pop_dead_suffix(state, self.liveness.live_vars_at(inst))
            if mark is not None and out is not None:
                self._check_restore_dominance(mark, inst)
                out.append(self._restore_fmp_inst(mark, self.fmp_var, inst.parent, inst))

        opcode = inst.opcode

        if opcode == "dalloca":
            state.stack.append(inst.output)
            if out is not None:
                out.extend(self._lower_dalloca(inst))
            return

        if opcode == "getfmp":
            # a read of the FMP virtual register: record the capture (its
            # derived-pointer region is unbounded above, so it is tracked
            # in the capture set, not at a stack position)
            state.captures.add(inst.output)
            if out is not None:
                inst.opcode = "assign"
                inst.operands = [self.fmp_var]
                out.append(inst)
            return

        if opcode == "setfmp":
            # an explicit FMP write: the producer asserts the new frame
            # layout (everything above the written value is free), which
            # supersedes every tracked mark and capture. Lowered to an
            # assign into the runner (multiply-assigned; MakeSSA repairs).
            state.clear()
            if out is not None:
                inst.opcode = "assign"
                inst.set_outputs([self.fmp_var])
                out.append(inst)
            return

        if opcode == "retfmp":
            # publishing return: plain `ret` of the values plus the hidden
            # adopted-FMP value (before the return PC)
            if out is not None:
                return_pc = inst.operands[-1]
                inst.opcode = "ret"
                inst.operands = [*inst.operands[:-1], self.fmp_var, return_pc]
                out.append(inst)
            return

        if opcode == "invoke":
            callee = InvokeLayout(self.function.ctx, inst).callee
            callee_info = self.dynamic_memory.get_info(callee) if callee is not None else None
            if out is not None:
                if callee_info is not None and callee_info.needs_fmp:
                    self._augment_invoke(inst, self.fmp_var)
                out.append(inst)
            if callee_info is not None and callee_info.returns_adopted_fmp:
                # the callee published a new frame layout over the FMP
                state.clear()
            return

        if out is not None:
            out.append(inst)

    def _is_reclaim_point(self, inst: IRInstruction) -> bool:
        if inst.opcode == "dalloca":
            return True
        if inst.opcode in ("jmp", "jnz", "djmp"):
            return True
        if inst.opcode == "invoke":
            callee = InvokeLayout(self.function.ctx, inst).callee
            return callee is not None and self.dynamic_memory.get_info(callee).needs_fmp
        return False

    def _pop_dead_suffix(self, state: _ReclaimState, live_vars) -> IRVariable | None:
        """
        Pop the longest dead, unpinned top segment of the tracked mark stack
        and return the restore target (the lowest popped mark) -- restoring
        the FMP to it frees exactly the popped allocations -- or None when
        nothing may be popped. A live or pinned mark blocks everything
        beneath it (a deeper restore would free its region).

        A possibly-live capture vetoes ALL popping, not only beneath itself:
        pointers derived from a getfmp output form an *upward-unbounded*
        region `[capture, oo)` -- e.g. the desugared-dret pack destinations
        extend above every later allocation until the closing setfmp -- so
        any restore, even to a mark pushed after the capture, frees
        addresses the capture may still reach. (This is deliberately
        stronger than the design note's "a pseudo-mark blocks popping
        anything beneath it", which is unsound for marks *above* the
        capture: a dalloca between a capture and its pack writes can be
        popped and re-allocated on top of the pack destinations.)
        """
        if not state.can_reclaim:
            return None
        if self._captures_veto(state, live_vars):
            return None

        stack = state.stack
        suffix_start = len(stack)
        while suffix_start > 0:
            mark = stack[suffix_start - 1]
            allocation = self._dalloca_allocation(self.base_ptrs, mark)
            if allocation is None:
                break
            if self._allocation_is_live(self.base_ptrs, allocation, live_vars):
                break
            suffix_start -= 1

        if suffix_start == len(stack):
            return None
        mark = stack[suffix_start]
        del stack[suffix_start:]
        return mark

    def _captures_veto(self, state: _ReclaimState, live_vars) -> bool:
        for capture in state.captures:
            if capture in self._pinned_captures:
                # escaped capture: derived pointers can re-enter through
                # memory where liveness cannot see them. Unknown == live.
                return True
            if any(var in live_vars for var in self._capture_derived[capture]):
                return True
        return False

    def _check_restore_dominance(self, mark: IRVariable, inst: IRInstruction) -> None:
        # a restore assigns `mark` to the FMP runner; SSA legality requires
        # the mark's definition to dominate the restore point. A mark that
        # survives the top-segment meet is the same SSA definition along all
        # predecessor paths, so its def dominates the join by construction;
        # assert it (cheap enough to keep on).
        def_bb = self._mark_def_bbs.get(mark)
        assert def_bb is not None, f"reclaim mark {mark} has no dalloca definition"
        assert self.dom.dominates(def_bb, inst.parent), (
            f"restore mark {mark} (defined in {def_bb.label}) does not "
            f"dominate the restore point in {inst.parent.label}"
        )

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
                for op in self._escaping_operands(inst):
                    for ptr in base_ptrs.get_possible_ptrs(op):
                        if ptr.base_alloca.inst.opcode == "dalloca":
                            pinned.add(ptr.base_alloca)

        return frozenset(pinned)

    def _escaping_operands(self, inst: IRInstruction) -> list[IRVariable]:
        """
        The variable operands of `inst` that escape SSA pointer tracking:
        occurrences not accounted for by the BasePtr propagation grammar or
        by the known-safe (address/length) positions of the shared memory-op
        descriptions. Fail closed.
        """
        if inst.opcode in _PTR_PROPAGATION_OPS:
            return []

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
        # an operand escapes if it occurs more often than safe positions
        # account for (`mstore %x, %x` stores the pointer value at its own
        # address).
        return [op for op in operands if operands.count(op) > safe.count(op)]

    def _compute_capture_facts(
        self, fn
    ) -> tuple[dict[IRVariable, set[IRVariable]], frozenset[IRVariable]]:
        """
        For every `getfmp` capture, conservatively compute the set of SSA
        variables derived from it and the set of captures that escape SSA
        tracking. BasePtrAnalysis intentionally assigns no pointer facts to
        getfmp outputs (they are untracked bases), so the derivation closure
        is recomputed here over the same propagation grammar; SSA liveness
        of the derived set then bounds the capture's reclaim veto. Escaped
        captures veto until the capture set is cleared. Fail closed.
        """
        insts = [inst for bb in fn.get_basic_blocks() for inst in bb.instructions]
        roots = [inst.output for inst in insts if inst.opcode == "getfmp"]
        if len(roots) == 0:
            return {}, frozenset()

        var_roots: dict[IRVariable, set[IRVariable]] = {root: {root} for root in roots}
        changed = True
        while changed:
            changed = False
            for inst in insts:
                if inst.opcode not in ("add", "sub", "assign", "phi") or inst.num_outputs != 1:
                    continue
                derived_roots: set[IRVariable] = set()
                for op in inst.get_input_variables():
                    derived_roots.update(var_roots.get(op, ()))
                if len(derived_roots) == 0:
                    continue
                current = var_roots.setdefault(inst.output, set())
                if not derived_roots <= current:
                    current.update(derived_roots)
                    changed = True

        pinned: set[IRVariable] = set()
        for inst in insts:
            for op in self._escaping_operands(inst):
                pinned.update(var_roots.get(op, ()))

        derived: dict[IRVariable, set[IRVariable]] = {root: set() for root in roots}
        for var, var_root_set in var_roots.items():
            for root in var_root_set:
                derived[root].add(var)
        return derived, frozenset(pinned)

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

    def _lower_dalloca(self, inst: IRInstruction) -> list[IRInstruction]:
        assert len(inst.operands) == 1, inst
        assert inst.num_outputs == 1, inst

        size = inst.operands[0]
        ptr_out = inst.output
        bb = inst.parent

        ceil_insts, aligned_var = self._ceil32_insts(size, bb, inst)
        bump_inst = IRInstruction("bump", [self.fmp_var, aligned_var], [ptr_out, self.fmp_var])
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

    def _augment_invoke(self, inst: IRInstruction, fmp_var: IRVariable) -> None:
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

        callee_info = self.dynamic_memory.get_info(callee)
        if callee_info.returns_adopted_fmp:
            # the adopted FMP is canonicalized straight into the runner
            layout.append_hidden_fmp_output(fmp_var)


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
