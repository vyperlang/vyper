from __future__ import annotations

from vyper.venom.analysis import (
    FCGGlobalAnalysis,
    IRAnalysesCache,
    IRGlobalAnalysesCache,
    LivenessAnalysis,
    MustHaltAnalysis,
)
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction

_EVM_STACK_LIMIT = 1024


class StackCleanupSafety:
    """
    Prove that dead values can remain on the physical stack in a must-halt region.

    This is a code-generation helper rather than an IR analysis: its bound is
    interpreted against the physical StackModel height known only during EVM
    lowering. The helper lives for one assembly-generation run and shares the
    same per-function analysis caches used by that run.

    Stack growth is deliberately overestimated from all distinct SSA values
    reachable in the region plus the largest instruction/callee transient.
    CFG or function-call cycles make the bound unknown and disable the elision.
    """

    def __init__(self, ctx: IRContext, analyses_caches: dict[IRFunction, IRAnalysesCache]) -> None:
        self.ctx = ctx
        self._analyses_caches = analyses_caches
        self._block_summaries: dict[IRBasicBlock, tuple[frozenset[IRVariable], int] | None] = {}
        self._function_growth: dict[IRFunction, int | None] = {}
        self._function_frame_growth: dict[IRFunction, int] = {}
        self._caller_stack_heights: dict[IRFunction, int | None] = {}

        self._entry_function = ctx.entry_function
        self._fcg: FCGGlobalAnalysis | None = None
        if ctx.entry_function is not None:
            global_cache = IRGlobalAnalysesCache(ctx, analyses_caches)
            self._fcg = global_cache.request_analysis(FCGGlobalAnalysis)

    def max_safe_current_height(self, bb: IRBasicBlock) -> int | None:
        """Return the largest current physical height for which elision is safe."""
        fn = bb.parent
        if bb not in self._get_must_halt(fn):
            return None

        caller_stack_height = self._max_caller_stack_height(fn, set())
        if caller_stack_height is None:
            return None

        growth = self._max_growth_from_block(bb, set(), {fn})
        if growth is None:
            return None

        return _EVM_STACK_LIMIT - caller_stack_height - growth

    def can_skip_cleanup(self, bb: IRBasicBlock, current_height: int) -> bool:
        max_height = self.max_safe_current_height(bb)
        return max_height is not None and current_height <= max_height

    def _max_caller_stack_height(
        self, fn: IRFunction, active_functions: set[IRFunction]
    ) -> int | None:
        if fn in self._caller_stack_heights:
            return self._caller_stack_heights[fn]
        if fn in active_functions:
            return None

        active_functions.add(fn)
        heights = [0] if fn is self._entry_function else []
        if self._fcg is not None:
            callers = {call_site.parent.parent for call_site in self._fcg.get_call_sites(fn)}
            for caller in callers:
                caller_height = self._max_caller_stack_height(caller, active_functions)
                if caller_height is None:
                    heights = []
                    break
                heights.append(caller_height + self._max_function_frame_growth(caller))
        active_functions.remove(fn)

        height = max(heights) if heights else None
        self._caller_stack_heights[fn] = height
        return height

    def _max_function_frame_growth(self, fn: IRFunction) -> int:
        if fn in self._function_frame_growth:
            return self._function_frame_growth[fn]

        liveness = self._get_liveness(fn)
        must_halt = self._get_must_halt(fn)
        terminal_variables: set[IRVariable] = set()
        early_return_outputs: set[IRVariable] = set()
        max_live = 0
        max_block_outputs = 0
        max_operands = 0

        for bb in fn.get_basic_blocks():
            max_block_outputs = max(
                max_block_outputs, sum(inst.num_outputs for inst in bb.instructions)
            )
            for inst in bb.instructions:
                live = liveness.live_vars_at(inst)
                max_live = max(max_live, len(live))
                max_operands = max(max_operands, len(inst.operands))
                if inst.opcode in ("offset", "phi"):
                    early_return_outputs.update(inst.get_outputs())
                if bb in must_halt:
                    terminal_variables.update(inst.get_input_variables())
                    terminal_variables.update(inst.get_outputs())
                    terminal_variables.update(live)

        # Outside a must-halt region, ordinary cleanup keeps the frame near
        # the live set. Inside one, every SSA value in the region may coexist
        # as retained junk. Track outputs from codegen paths which bypass
        # normal dead-output cleanup (`offset` and `phi`) across blocks too.
        growth = (
            max_live
            + len(terminal_variables)
            + len(early_return_outputs)
            + max_block_outputs
            + max_operands
            + 2
        )
        self._function_frame_growth[fn] = growth
        return growth

    def _max_growth_from_function(
        self, fn: IRFunction, active_blocks: set[IRBasicBlock], active_functions: set[IRFunction]
    ) -> int | None:
        if fn in self._function_growth:
            return self._function_growth[fn]
        if fn in active_functions:
            return None

        active_functions.add(fn)
        try:
            growth = self._max_growth_from_block(fn.entry, active_blocks, active_functions)
        finally:
            active_functions.remove(fn)
        self._function_growth[fn] = growth
        return growth

    def _max_growth_from_block(
        self, bb: IRBasicBlock, active_blocks: set[IRBasicBlock], active_functions: set[IRFunction]
    ) -> int | None:
        summary = self._stack_growth_summary(bb, active_blocks, active_functions)
        if summary is None:
            return None
        variables, transient = summary
        return len(variables) + transient

    def _stack_growth_summary(
        self, bb: IRBasicBlock, active_blocks: set[IRBasicBlock], active_functions: set[IRFunction]
    ) -> tuple[frozenset[IRVariable], int] | None:
        if bb in self._block_summaries:
            return self._block_summaries[bb]
        if bb in active_blocks:
            return None

        active_blocks.add(bb)
        try:
            # A distinct SSA value can occupy at most one persistent physical
            # slot. A consumed copy of each operand can coexist with those slots;
            # two more cover lowering details such as jump labels, bump's DUP,
            # and the one-slot transient used by deep stack spilling.
            variables: set[IRVariable] = set()
            max_transient = 0
            liveness = self._get_liveness(bb.parent)
            for inst in bb.instructions:
                variables.update(inst.get_input_variables())
                variables.update(inst.get_outputs())
                variables.update(liveness.live_vars_at(inst))
                inst_transient = len(inst.operands) + 2

                if inst.opcode == "invoke":
                    target = inst.operands[0]
                    assert isinstance(target, IRLabel)
                    callee = self.ctx.get_function(target)
                    callee_growth = self._max_growth_from_function(
                        callee, active_blocks, active_functions
                    )
                    if callee_growth is None:
                        self._block_summaries[bb] = None
                        return None
                    inst_transient += callee_growth

                max_transient = max(max_transient, inst_transient)

            for successor in bb.out_bbs:
                successor_summary = self._stack_growth_summary(
                    successor, active_blocks, active_functions
                )
                if successor_summary is None:
                    self._block_summaries[bb] = None
                    return None
                successor_variables, successor_transient = successor_summary
                variables.update(successor_variables)
                max_transient = max(max_transient, successor_transient)

            summary = (frozenset(variables), max_transient)
            self._block_summaries[bb] = summary
            return summary
        finally:
            active_blocks.remove(bb)

    def _get_liveness(self, fn: IRFunction) -> LivenessAnalysis:
        return self._analyses_caches[fn].request_analysis(LivenessAnalysis)

    def _get_must_halt(self, fn: IRFunction) -> frozenset[IRBasicBlock]:
        analysis = self._analyses_caches[fn].request_analysis(MustHaltAnalysis)
        return analysis.must_halt
