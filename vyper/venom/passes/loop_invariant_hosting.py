from vyper.utils import OrderedSet
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.analysis.loop_detection import NaturalLoopDetectionAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.effects import EMPTY, Effects
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


def _ignore_instruction(inst: IRInstruction) -> bool:
    return (
        inst.is_bb_terminator
        or inst.opcode == "returndatasize"
        or inst.opcode == "phi"
        or (inst.opcode == "add" and isinstance(inst.operands[1], IRLabel))
        or inst.opcode == "assign"
    )


# must check if it has as operand as literal because
# there are cases when the assign just moves value
# from one variable to another
def _is_correct_assign(inst: IRInstruction) -> bool:
    return inst.opcode == "assign" and isinstance(inst.operands[0], IRLiteral)


class LoopInvariantHoisting(IRPass):
    """
    This pass detects invariants in loops and hoists them above the loop body.
    Any VOLATILE_INSTRUCTIONS, BB_TERMINATORS CFG_ALTERING_INSTRUCTIONS are ignored
    """

    function: IRFunction
    loops: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]
    dfg: DFGAnalysis

    def run_pass(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)  # type: ignore
        loops = self.analyses_cache.request_analysis(NaturalLoopDetectionAnalysis)
        assert isinstance(loops, NaturalLoopDetectionAnalysis)
        self.loops = loops.loops
        invalidate = False
        while True:
            change = False
            for from_bb, loop in self.loops.items():
                hoistable: list[IRInstruction] = self._get_hoistable_loop(from_bb, loop)
                if len(hoistable) == 0:
                    continue
                change |= True
                self._hoist(from_bb, hoistable)
            if not change:
                break
            invalidate = True

        # only need to invalidate if you did some hoisting
        if invalidate:
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _hoist(self, target_bb: IRBasicBlock, hoistable: list[IRInstruction]):
        for inst in hoistable:
            bb = inst.parent
            bb.remove_instruction(inst)
            target_bb.insert_instruction(inst, index=len(target_bb.instructions) - 1)

    def _get_loop_effects_write(self, loop: OrderedSet[IRBasicBlock]) -> Effects:
        res: Effects = EMPTY
        for bb in loop:
            assert isinstance(bb, IRBasicBlock)  # help mypy
            for inst in bb.instructions:
                res |= inst.get_write_effects()
        return res

    def _get_hoistable_loop(
        self, from_bb: IRBasicBlock, loop: OrderedSet[IRBasicBlock]
    ) -> list[IRInstruction]:
        result: list[IRInstruction] = []
        loop_effects = self._get_loop_effects_write(loop)
        for bb in loop:
            result.extend(self._get_hoistable_bb(bb, from_bb, loop_effects))
        return result

    def _get_hoistable_bb(
        self, bb: IRBasicBlock, loop_idx: IRBasicBlock, loop_effects: Effects
    ) -> list[IRInstruction]:
        result: list[IRInstruction] = []
        for inst in bb.instructions:
            if self._can_hoist_instruction_ignore_assign(inst, self.loops[loop_idx], loop_effects):
                result.extend(self._assign_dependencies(inst, loop_idx))
                result.append(inst)

        return result

    # query assign dependacies of instruction (they are not handled otherwise)
    def _assign_dependencies(
        self, inst: IRInstruction, loop_idx: IRBasicBlock
    ) -> list[IRInstruction]:
        result: list[IRInstruction] = []
        for var in inst.get_input_variables():
            source_inst = self.dfg.get_producing_instruction(var)
            assert isinstance(source_inst, IRInstruction)
            if not _is_correct_assign(source_inst):
                continue
            for bb in self.loops[loop_idx]:
                if source_inst.parent == bb:
                    result.append(source_inst)
        return result

    # since the assigns are always hoistable this ignores
    # assigns in analysis (their are hoisted if some instrution is dependent on them)
    def _can_hoist_instruction_ignore_assign(
        self, inst: IRInstruction, loop: OrderedSet[IRBasicBlock], loop_effects: Effects
    ) -> bool:
        if (inst.get_read_effects() & loop_effects) != EMPTY:
            return False
        if _ignore_instruction(inst):
            return False
        for bb in loop:
            if self._dependent_in_bb(inst, bb):
                return False
        return True

    def _dependent_in_bb(self, inst: IRInstruction, bb: IRBasicBlock):
        for in_var in inst.get_input_variables():
            assert isinstance(in_var, IRVariable)
            source_ins = self.dfg.get_producing_instruction(in_var)
            assert isinstance(source_ins, IRInstruction)

            # ignores assign since all assigns are independant
            # and can be always hoisted
            if _is_correct_assign(source_ins):
                continue

            if source_ins.parent == bb:
                return True
        return False
