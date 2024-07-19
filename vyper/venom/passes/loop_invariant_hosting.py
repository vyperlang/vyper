from vyper.utils import OrderedSet
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.analysis.loop_detection import LoopDetectionAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


def _ignore_instruction(instruction: IRInstruction) -> bool:
    return (
        instruction.is_volatile
        or instruction.is_bb_terminator
        or instruction.opcode == "returndatasize"
        or instruction.opcode == "phi"
    )


def _is_correct_store(instruction: IRInstruction) -> bool:
    return instruction.opcode == "store"


class LoopInvariantHoisting(IRPass):
    """
    This pass detects invariants in loops and hoists them above the loop body.
    Any VOLATILE_INSTRUCTIONS, BB_TERMINATORS CFG_ALTERING_INSTRUCTIONS are ignored
    """

    function: IRFunction
    loop_analysis: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]
    dfg: DFGAnalysis

    def run_pass(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        loops = self.analyses_cache.request_analysis(LoopDetectionAnalysis)
        self.loop_analysis = loops.loops
        invalidate_dependant = False
        while True:
            change = False
            for from_bb, loop in self.loop_analysis.items():
                hoistable: list[IRInstruction] = self._get_hoistable_loop(from_bb, loop)
                if len(hoistable) == 0:
                    continue
                change |= True
                self._hoist(from_bb, hoistable)
            if not change:
                break
            invalidate_dependant = True

        # only need to invalidate if you did some hoisting
        if invalidate_dependant:
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _hoist(self, target_bb: IRBasicBlock, hoistable: list[IRInstruction]):
        for inst in hoistable:
            bb = inst.parent
            bb.remove_instruction(inst)
            target_bb.insert_instruction(inst, index=len(target_bb.instructions) - 1)

    def _get_hoistable_loop(
        self, from_bb: IRBasicBlock, loop: OrderedSet[IRBasicBlock]
    ) -> list[IRInstruction]:
        result: list[IRInstruction] = []
        for bb in loop:
            result.extend(self._get_hoistable_bb(bb, from_bb))
        return result

    def _get_hoistable_bb(self, bb: IRBasicBlock, loop_idx: IRBasicBlock) -> list[IRInstruction]:
        result: list[IRInstruction] = []
        for instruction in bb.instructions:
            if self._can_hoist_instruction_ignore_stores(instruction, self.loop_analysis[loop_idx]):
                result.extend(self._store_dependencies(instruction, loop_idx))
                result.append(instruction)

        return result

    # query store dependacies of instruction (they are not handled otherwise)
    def _store_dependencies(
        self, inst: IRInstruction, loop_idx: IRBasicBlock
    ) -> list[IRInstruction]:
        result: list[IRInstruction] = []
        for var in inst.get_input_variables():
            source_inst = self.dfg.get_producing_instruction(var)
            assert isinstance(source_inst, IRInstruction)
            if _is_correct_store(source_inst):
                for bb in self.loop_analysis[loop_idx]:
                    if source_inst.parent == bb:
                        result.append(source_inst)
        return result

    # since the stores are always hoistable this ignores
    # stores in analysis (their are hoisted if some instrution is dependent on them)
    def _can_hoist_instruction_ignore_stores(
        self, instruction: IRInstruction, loop: OrderedSet[IRBasicBlock]
    ) -> bool:
        if _ignore_instruction(instruction) or _is_correct_store(instruction):
            return False
        for bb in loop:
            if self._dependant_in_bb(instruction, bb):
                return False
        return True

    def _dependant_in_bb(self, instruction: IRInstruction, bb: IRBasicBlock):
        for in_var in instruction.get_input_variables():
            assert isinstance(in_var, IRVariable)
            source_ins = self.dfg._dfg_outputs[in_var]

            # ignores stores since all stores are independant
            # and can be always hoisted
            if _is_correct_store(source_ins):
                continue

            if source_ins.parent == bb:
                return True
        return False
