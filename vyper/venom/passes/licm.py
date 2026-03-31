from typing import Iterator

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, DominatorTreeAnalysis, IRAnalysesCache
from vyper.venom.analysis.loop import LoopAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IROperand
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

        for loop in self.loop_analysis.loops:
            self._process_loop(loop)

    def _get_phi_instructions(self, bb: IRBasicBlock) -> Iterator[IRInstruction]:
        """Get all phi instructions in a basic block."""
        for inst in bb.instructions:
            if inst.opcode != "phi":
                break  # phis are always at the beginning
            yield inst

    def _get_or_insert_preheader(self, loop) -> IRBasicBlock:
        """
        Get the loop preheader, or create one if it doesn't exist.

        A preheader is a single block that is the only predecessor of the
        loop header from outside the loop. If multiple outside predecessors
        exist, we create a new preheader and redirect them through it.
        """
        # Preheader already exists, no need to split edge.
        if (preheader := self.loop_analysis.get_preheader(loop)) is not None:
            return preheader

        fn = self.function

        # Create a new block
        preheader_label = IRLabel(f"preheader_{loop.header.label.value}")
        preheader = IRBasicBlock(preheader_label, fn)

        # Add jump to preheader
        preheader.append_instruction("jmp", loop.header.label)

        outside_preds = [p for p in self.cfg.cfg_in(loop.header) if p not in loop.body]

        # Update terminators to go to preheader instead of our loop header
        for pred in outside_preds:
            pred.instructions[-1].replace_label_operands({loop.header.label: preheader_label})

        # Collect outside phi operands and strip them from header phis
        outside_by_phi: dict[IRInstruction, list[tuple[IRLabel, IROperand]]] = {}
        for phi in self._get_phi_instructions(loop.header):
            inside = []
            outside = []
            for lbl, val in phi.phi_operands:
                if self.function.get_basic_block(lbl.value) in loop.body:
                    inside.extend([lbl, val])
                else:
                    outside.append((lbl, val))

            if outside:
                phi.operands = inside  # strip outside entries
                outside_by_phi[phi] = outside

        # Create preheader phis and add preheader entries to header phis
        # TODO: if only one entry, skip phi and use value directly
        for phi, entries in outside_by_phi.items():
            new_var = self.function.get_next_variable()

            # Create phi in preheader with all outside entries
            args = [item for lbl, val in entries for item in (lbl, val)]
            new_phi = IRInstruction("phi", args, [new_var])
            preheader.insert_instruction(new_phi, 0)

            # Add preheader entry to header phi
            phi.operands.extend([preheader_label, new_var])

        fn.append_basic_block(preheader)
        return preheader

    def _is_hoistable(self, inst: IRInstruction, loop) -> bool:
        """
        Check if an instruction can be hoisted to the preheader.

        An instruction is hoistable if:
        1. It has no side effects (not volatile)
        2. It's not a phi instruction
        3. It's loop-invariant (all operands defined outside or invariant)
        4. Its block dominates all loop exits (unless allow_speculative)
        """
        # Handles no side effects requirement
        if inst.is_volatile:
            return False

        # Phi instructions almost always have side effects, so just skip them
        if inst.opcode == "phi":
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

    def _process_loop(self, loop):
        preheader = self._get_or_insert_preheader(loop)

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

            if not inst.output:
                continue

            for use in self.dfg.get_uses(inst.output):
                if use.parent in loop.body:
                    worklist.append(use)

        for inst in self.invariant:
            # Remove from original block
            inst.parent.instructions.remove(inst)
            # Insert into preheader
            preheader.insert_instruction(inst, len(preheader.instructions) - 1)
