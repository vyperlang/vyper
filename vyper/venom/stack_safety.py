from __future__ import annotations

from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import CFGAnalysis, FCGGlobalAnalysis, IRGlobalAnalysis, MustHaltAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable
from vyper.venom.function import IRFunction

_EVM_STACK_LIMIT = 1024


class StackCleanupSafety(IRGlobalAnalysis):
    """Prove that dead stack slots can remain in a must-halt region.

    The first cleanup elision on a runtime path starts from an accurate physical
    stack height.  Its bound covers every distinct SSA value reachable after
    that edge, the largest instruction transient, and transitive callees.  It
    therefore also covers later elisions, whose codegen model height may depend
    on which predecessor was visited first.

    CFG cycles make the regional bound unknown and disable the elision.
    Recursive function calls are invalid Venom.  Codegen verifies the predicted
    heights against the EVM operations it emits; an underestimated lowering
    bound is a compile-time failure rather than a possible runtime stack
    overflow.
    """

    def analyze(self) -> None:
        self._block_summaries: dict[IRBasicBlock, tuple[frozenset[IRVariable], int] | None] = {}
        self._function_growth: dict[IRFunction, int | None] = {}
        self._function_frame_growth: dict[IRFunction, int] = {}
        self._caller_stack_heights: dict[IRFunction, int | None] = {}
        self._safe_current_heights: dict[IRBasicBlock, int | None] = {}

        self._entry_function = self.ctx.entry_function
        self._fcg: FCGGlobalAnalysis | None = None
        if self._entry_function is not None:
            self._fcg = self.global_analyses_cache.request_analysis(FCGGlobalAnalysis)

    def max_safe_current_height(self, bb: IRBasicBlock) -> int | None:
        """Return the largest current function-local height safe for elision."""
        if bb in self._safe_current_heights:
            return self._safe_current_heights[bb]

        fn = bb.parent
        if bb not in self._get_must_halt(fn):
            self._safe_current_heights[bb] = None
            return None

        caller_stack_height = self._max_caller_stack_height(fn, set())
        if caller_stack_height is None:
            self._safe_current_heights[bb] = None
            return None

        growth = self._max_growth_from_block(bb, set(), {fn})
        if growth is None:
            self._safe_current_heights[bb] = None
            return None

        ret = _EVM_STACK_LIMIT - caller_stack_height - growth
        self._safe_current_heights[bb] = ret
        return ret

    def stack_height_bound(self, bb: IRBasicBlock, current_height: int) -> int | None:
        """Return the promised maximum local height, or ``None`` if unsafe."""
        max_current_height = self.max_safe_current_height(bb)
        if max_current_height is None or current_height > max_current_height:
            return None

        growth = self._max_growth_from_block(bb, set(), {bb.parent})
        assert growth is not None  # established by max_safe_current_height()
        return current_height + growth

    def can_skip_cleanup(self, bb: IRBasicBlock, current_height: int) -> bool:
        return self.stack_height_bound(bb, current_height) is not None

    def verify_codegen(self, function_peak_heights: dict[IRFunction, int]) -> None:
        """Verify the frame and regional terms used to compose stack bounds."""
        for fn, actual_height in function_peak_heights.items():
            frame_height = self._max_function_frame_growth(fn)
            if actual_height > frame_height:
                raise CompilerPanic(
                    f"Stack cleanup safety underestimated {fn.name}: "
                    f"codegen reached {actual_height}, frame bound was {frame_height}"
                )

            regional_height = self._max_growth_from_function(fn, set())
            if regional_height is not None and actual_height > regional_height:
                raise CompilerPanic(
                    f"Stack cleanup safety underestimated {fn.name}: "
                    f"codegen reached {actual_height}, regional bound was {regional_height}"
                )

    def _max_caller_stack_height(
        self, fn: IRFunction, active_functions: set[IRFunction]
    ) -> int | None:
        if fn in self._caller_stack_heights:
            return self._caller_stack_heights[fn]
        assert fn not in active_functions, "recursive function call"

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

        height = max(heights) if len(heights) > 0 else None
        self._caller_stack_heights[fn] = height
        return height

    def _max_function_frame_growth(self, fn: IRFunction) -> int:
        if fn in self._function_frame_growth:
            return self._function_frame_growth[fn]

        # At most one persistent slot exists for each SSA value.  Operand
        # copies and lowering details are temporary and are covered by the
        # largest per-instruction transient.  Codegen verifies this term.
        variables: set[IRVariable] = set()
        max_transient = 0
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                variables.update(inst.get_input_variables())
                variables.update(inst.get_outputs())
                max_transient = max(max_transient, len(inst.operands) + 2)

        growth = len(variables) + max_transient
        self._function_frame_growth[fn] = growth
        return growth

    def _max_growth_from_function(
        self, fn: IRFunction, active_functions: set[IRFunction]
    ) -> int | None:
        if fn in self._function_growth:
            return self._function_growth[fn]
        assert fn not in active_functions, "recursive function call"

        active_functions.add(fn)
        try:
            growth = self._max_growth_from_block(fn.entry, set(), active_functions)
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
            variables: set[IRVariable] = set()
            max_transient = 0
            for inst in bb.instructions:
                variables.update(inst.get_input_variables())
                variables.update(inst.get_outputs())
                inst_transient = len(inst.operands) + 2

                if inst.opcode == "invoke":
                    target = inst.operands[0]
                    assert isinstance(target, IRLabel)
                    callee = self.ctx.get_function(target)
                    callee_growth = self._max_growth_from_function(callee, active_functions)
                    if callee_growth is None:
                        self._block_summaries[bb] = None
                        return None
                    inst_transient += callee_growth

                max_transient = max(max_transient, inst_transient)

            cfg = self._get_cfg(bb.parent)
            for successor in cfg.cfg_out(bb):
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

    def _get_cfg(self, fn: IRFunction) -> CFGAnalysis:
        return self.analyses_caches[fn].request_analysis(CFGAnalysis)

    def _get_must_halt(self, fn: IRFunction) -> frozenset[IRBasicBlock]:
        analysis = self.analyses_caches[fn].request_analysis(MustHaltAnalysis)
        return analysis.must_halt

    def invalidate(self) -> None:
        del self._block_summaries
        del self._function_growth
        del self._function_frame_growth
        del self._caller_stack_heights
        del self._safe_current_heights
        del self._entry_function
        del self._fcg
