from vyper.utils import OrderedSet
from vyper.venom import effects
from vyper.venom.analysis import (
    CFGAnalysis,
    DFGAnalysis,
    DominatorTreeAnalysis,
    IRAnalysesCache,
    LivenessAnalysis,
)
from vyper.venom.analysis.loop import Loop, LoopAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class LICMPass(IRPass):
    """
    Loop Invariant Code Motion pass.
    Hoists loop-invariant instructions to the loop preheader.

    Args:
        allow_speculative: If True, hoist invariants even from blocks that
            don't dominate all exits. This may cause extra work if the loop
            runs 0 iterations. Default is False (conservative).

            NOTE: In the future, we should integrate range-analysis into LICM to
            have a better heuristic for when this should be enabled
    """

    def __init__(
        self, analyses_cache: IRAnalysesCache, function: IRFunction, allow_speculative: bool = False
    ):
        super().__init__(analyses_cache, function)
        self.allow_speculative = allow_speculative

    def run_pass(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.loop_analysis = self.analyses_cache.request_analysis(LoopAnalysis)

        self.changed = False
        for loop in self.loop_analysis.loops:
            self._process_loop(loop)

        if self.changed:
            self.analyses_cache.invalidate_analysis(CFGAnalysis)
            self.analyses_cache.invalidate_analysis(DFGAnalysis)
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)
            self.analyses_cache.invalidate_analysis(LoopAnalysis)

    def _get_preheader(self, loop: Loop) -> IRBasicBlock | None:
        """
        Get the loop preheader if it exists.

        Returns None if no valid preheader exists. Unlike PR #4819's approach,
        we don't create preheaders - we skip loops without them to avoid
        CFG modification complexity.
        """
        return self.loop_analysis.get_preheader(loop)

    def _is_hoistable(self, inst: IRInstruction, loop: Loop) -> bool:
        """
        Check if an instruction can be hoisted to the preheader.

        An instruction is hoistable if:
        1. It has no side effects (not volatile, no writes except MSIZE)
        2. Its reads don't conflict with loop writes
        3. It's not a phi instruction or terminator
        4. It's loop-invariant (all operands defined outside or invariant)
        5. Its block dominates all loop exits (unless allow_speculative)
        """
        if inst.is_volatile or inst.is_bb_terminator:
            return False

        if inst.opcode == "phi":
            return False

        # Check write effects (allow MSIZE since it's observational)
        if inst.get_write_effects() & ~effects.MSIZE:
            return False

        # Check if instruction reads something the loop writes
        if inst.get_read_effects() & self.loop_write_effects:
            return False

        if not self._is_invariant(inst, loop):
            return False

        # Must dominate all loop exits to avoid extra work (unless speculative)
        if not self.allow_speculative:
            for exit_bb in self.loop_analysis.get_exit_nodes(loop):
                if not self.dom.dominates(inst.parent, exit_bb):
                    return False

        return True

    def _is_invariant(self, inst: IRInstruction, loop) -> bool:
        """
        Check if an instruction is loop-invariant.

        An instruction is invariant if all its operands are either:
        - Defined outside the loop
        - Produced by another invariant instruction
        """
        for op in inst.get_input_variables():
            prod = self.dfg.get_producing_instruction(op)
            if prod is None:
                continue  # literal or param, invariant
            if prod.parent not in loop.body:
                continue  # defined outside loop, invariant
            if prod in self.invariant:
                continue  # already marked invariant
            return False
        return True

    def _collect_loop_write_effects(self, loop: Loop) -> effects.Effects:
        """Collect all write effects from instructions in the loop."""
        result = effects.EMPTY
        for bb in loop.body:
            for inst in bb.instructions:
                result |= inst.get_write_effects()
        return result

    def _process_loop(self, loop: Loop):
        preheader = self._get_preheader(loop)
        if preheader is None:
            return  # Can't hoist without a preheader

        self.loop_write_effects = self._collect_loop_write_effects(loop)
        self.invariant: OrderedSet[IRInstruction] = OrderedSet()
        worklist = []
        for bb in loop.body:
            for inst in bb.instructions:
                worklist.append(inst)

        while worklist:
            inst = worklist.pop()

            if not self._is_hoistable(inst, loop):
                continue

            self.invariant.add(inst)

            if not inst.has_outputs:
                continue

            for out in inst.get_outputs():
                for use in self.dfg.get_uses(out):
                    if use.parent in loop.body:
                        worklist.append(use)

        if len(self.invariant) > 0:
            self.changed = True

        for inst in self.invariant:
            # Remove from original block
            inst.parent.instructions.remove(inst)
            # Insert into preheader
            preheader.insert_instruction(inst, len(preheader.instructions) - 1)
