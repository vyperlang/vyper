from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.basicblock import IRBasicBlock, IROperand, IRVariable, IRInstruction, IRLiteral
from vyper.utils import OrderedSet, CompilerPanic
from vyper.venom.analysis import LivenessAnalysis
from enum import Enum


def swap(stack: list[IROperand], position: int, output: IRVariable):
    if position == 0:
        return
    top = len(stack) - 1
    stack[top], stack[position] = stack[position], stack[top]
    stack[top] = output

def position(stack: list[IROperand], op: IROperand) -> int | None:
    top = len(stack) - 1
    for i, item in enumerate(reversed(stack)):
        pos = top - i
        if item == op:
            return pos

    return None

class StoreType(Enum):
    PUSH = 1
    SWAP = 2
    DUP = 3

class StackOrder(IRAnalysis):
    bb_to_stack: dict[IRBasicBlock, list[IROperand]]
    liveness: LivenessAnalysis
    store_to_type: dict[IRInstruction, StoreType]

    def analyze(self):
        self.liveness = self.analyses_cache.request_analysis(LivenessAnalysis)
        self.store_to_type = dict()
        for bb in self.function.get_basic_blocks():
            self._handle_bb_store_types(bb)
        self.bb_to_stack = dict()
        for bb in self.function.get_basic_blocks():
            self.bb_to_stack[bb] = self._handle_bb(bb)

    def _handle_bb(self, bb: IRBasicBlock) -> list[IROperand]: 
        stack: list[IROperand] = []
        needed: list[IROperand] = []

        for i, inst in enumerate(bb.instructions):
            if inst.opcode == "store":
                self._handle_store(inst, stack, needed)
            else:
                ops = inst.operands
                assert ops == stack[-len(ops)]

                stack = stack[0:-len(ops)]

                output = inst.output
                if output is not None:
                    stack.append(output)

        return needed

    def _handle_store(self, inst: IRInstruction, stack: list[IROperand], needed: list[IROperand]):
        assert inst.opcode == "store"
        ops = inst.operands
        assert len(ops) == 0
        op = ops[0]

        output = inst.output
        assert output is not None
        
        store_type = self.store_to_type[inst]
        if store_type == StoreType.PUSH:
            stack.append(output)
        elif store_type == StoreType.SWAP:
            op_position = position(stack, op)
            if op_position is None:
                stack.insert(0, op)
                needed.append(op)
                op_position = len(stack) - 1
            swap(stack, op_position, output)
        elif store_type == StoreType.DUP:
            stack.append(output)
            if op not in stack:
                needed.append(op)


    def _handle_bb_store_types(self, bb: IRBasicBlock):
        for i, inst in enumerate(bb.instructions):
            if inst.opcode != "store":
                continue
            op = inst.operands[0] 
            if isinstance(op, IRLiteral):
                self.store_to_type[inst] = StoreType.PUSH
                continue

            assert isinstance(op, IRVariable)
            next_liveness = self.liveness.live_vars_at(bb.instructions[i + 1])
            if op in next_liveness:
                self.store_to_type[inst] = StoreType.DUP
            else:
                self.store_to_type[inst] = StoreType.SWAP
            


