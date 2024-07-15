from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.analysis.loop_detection import LoopDetectionAnalysis
from vyper.venom.basicblock import (
    BB_TERMINATORS,
    CFG_ALTERING_INSTRUCTIONS,
    VOLATILE_INSTRUCTIONS,
    IRBasicBlock,
    IRInstruction,
    IRVariable,
)
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class LoopInvariantHoisting(IRPass):
    """
    This pass detects invariants in loops and hoists them above the loop body.
    Any VOLATILE_INSTRUCTIONS, BB_TERMINATORS CFG_ALTERING_INSTRUCTIONS are ignored
    """
    from typing import Iterator

    function: IRFunction
    loops: dict[IRBasicBlock, list[IRBasicBlock]]
    dfg: DFGAnalysis

    def run_pass(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        loops = self.analyses_cache.request_analysis(LoopDetectionAnalysis)
        self.loops = loops.loops
        while True:
            change = False
            for from_bb, loop in self.loops.items():
                hoistable: list[tuple[IRBasicBlock, int, IRInstruction]] = self._get_hoistable_loop(
                    from_bb, loop
                )
                if len(hoistable) == 0:
                    continue
                change |= True
                self._hoist(hoistable)
            if not change:
                break
            # I have this inside the loop because I dont need to
            # invalidate if you dont hoist anything
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _hoist(self, hoistable: list[tuple[IRBasicBlock, int, IRInstruction]]):
        for loop_idx, bb_idx, inst in hoistable:
            loop = self.loops[loop_idx]
            loop[bb_idx].remove_instruction(inst)
            bb_before: IRBasicBlock = loop_idx
            bb_before.insert_instruction(inst, index=len(bb_before.instructions) - 1)

    def _get_hoistable_loop(
        self, from_bb: IRBasicBlock, loop: list[IRBasicBlock]
    ) -> list[tuple[IRBasicBlock, int, IRInstruction]]:
        result: list[tuple[IRBasicBlock, int, IRInstruction]] = []
        for bb_idx, bb in enumerate(loop):
            result.extend(self._get_hoistable_bb(bb, from_bb, bb_idx))
        return result

    def _get_hoistable_bb(
        self, bb: IRBasicBlock, loop_idx: IRBasicBlock, bb_idx
    ) -> list[tuple[IRBasicBlock, int, IRInstruction]]:
        result: list[tuple[IRBasicBlock, int, IRInstruction]] = []
        for instruction in bb.instructions:
            if self._can_hoist_instruction(instruction, self.loops[loop_idx]):
                result.append((loop_idx, bb_idx, instruction))

        return result

    def _can_hoist_instruction(self, instruction: IRInstruction, loop: list[IRBasicBlock]) -> bool:
        if (
            instruction.opcode in VOLATILE_INSTRUCTIONS
            or instruction.opcode in BB_TERMINATORS
            or instruction.opcode in CFG_ALTERING_INSTRUCTIONS
        ):
            return False
        for bb in loop:
            if self._in_bb(instruction, bb):
                return False
        return True

    def _in_bb(self, instruction: IRInstruction, bb: IRBasicBlock):
        for in_var in instruction.get_input_variables():
            assert isinstance(in_var, IRVariable)
            source_ins = self.dfg._dfg_outputs[in_var]
            if source_ins in bb.instructions:
                return True
        return False
