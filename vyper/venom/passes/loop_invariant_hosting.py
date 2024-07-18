from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.analysis.loop_detection import LoopDetectionAnalysis
from vyper.venom.analysis.dup_requirements import DupRequirementsAnalysis
from vyper.venom.basicblock import (
    BB_TERMINATORS,
    CFG_ALTERING_INSTRUCTIONS,
    VOLATILE_INSTRUCTIONS,
    IRBasicBlock,
    IRInstruction,
    IRVariable,
    IRLiteral
)
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass

from vyper.utils import OrderedSet


def _ignore_instruction(instruction : IRInstruction) -> bool:
    return (
        instruction.is_volatile
        or instruction.is_bb_terminator
        or instruction.opcode == "returndatasize"
        or instruction.opcode == "phi"
    )

def _is_correct_store(instruction : IRInstruction) -> bool:
    return (
        instruction.opcode == "store"
        and len(instruction.operands) == 1
        and isinstance(instruction.operands[0], IRLiteral)
    )

class LoopInvariantHoisting(IRPass):
    """
    This pass detects invariants in loops and hoists them above the loop body.
    Any VOLATILE_INSTRUCTIONS, BB_TERMINATORS CFG_ALTERING_INSTRUCTIONS are ignored
    """
    from typing import Iterator

    function: IRFunction
    loops: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]
    dfg: DFGAnalysis

    def run_pass(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        loops = self.analyses_cache.request_analysis(LoopDetectionAnalysis)
        self.loops = loops.loops
        while True:
            change = False
            for from_bb, loop in self.loops.items():
                hoistable: list[tuple[IRBasicBlock, IRBasicBlock, IRInstruction]] = self._get_hoistable_loop(
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

    def _hoist(self, hoistable: list[tuple[IRBasicBlock, IRBasicBlock, IRInstruction]]):
        for loop_idx, bb, inst in hoistable:
            bb.remove_instruction(inst)
            bb_before: IRBasicBlock = loop_idx
            bb_before.insert_instruction(inst, index=len(bb_before.instructions) - 1)

    def _get_hoistable_loop(
        self, from_bb: IRBasicBlock, loop: OrderedSet[IRBasicBlock]
    ) -> list[tuple[IRBasicBlock, IRBasicBlock, IRInstruction]]:
        result: list[tuple[IRBasicBlock, IRBasicBlock, IRInstruction]] = []
        for bb in loop:
            result.extend(self._get_hoistable_bb(bb, from_bb))
        return result

    def _get_hoistable_bb(
        self, bb: IRBasicBlock, loop_idx: IRBasicBlock
    ) -> list[tuple[IRBasicBlock, IRBasicBlock, IRInstruction]]:
        result: list[tuple[IRBasicBlock, IRBasicBlock, IRInstruction]] = []
        for instruction in bb.instructions:
            if self._can_hoist_instruction(instruction, self.loops[loop_idx]):
                result.append((loop_idx, bb, instruction))

        return result

    def _can_hoist_instruction(self, instruction: IRInstruction, loop: OrderedSet[IRBasicBlock]) -> bool:
        if _ignore_instruction(instruction):
            return False
        for bb in loop:
            if self._in_bb(instruction, bb):
                return False

        if _is_correct_store(instruction):
            for used_instruction in self.dfg.get_uses(instruction.output):
                if not self._can_hoist_instruction_ignore_stores(used_instruction, loop):
                    return False

        return True

    def _in_bb(self, instruction: IRInstruction, bb: IRBasicBlock):
        for in_var in instruction.get_input_variables():
            assert isinstance(in_var, IRVariable)
            source_ins = self.dfg._dfg_outputs[in_var]
            if source_ins in bb.instructions:
                return True
        return False

    def _can_hoist_instruction_ignore_stores(self, instruction: IRInstruction, loop: OrderedSet[IRBasicBlock]) -> bool:
        if _ignore_instruction(instruction):
            return False
        for bb in loop:
            if self._in_bb_ignore_store(instruction, bb):
                return False
        return True

    def _in_bb_ignore_store(self, instruction: IRInstruction, bb: IRBasicBlock):
        for in_var in instruction.get_input_variables():
            assert isinstance(in_var, IRVariable)
            source_ins = self.dfg._dfg_outputs[in_var]
            if _is_correct_store(source_ins):
                continue

            if source_ins in bb.instructions:
                return True
        return False

