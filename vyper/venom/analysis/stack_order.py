from enum import Enum

from vyper.venom.analysis import LivenessAnalysis
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.function import IRFunction


def swap(stack: list[IROperand], position: int, output: IROperand | None = None):
    top = len(stack) - 1
    position = top - position
    if position == top:
        if output is not None:
            stack[top] = output
        return
    stack[top], stack[position] = stack[position], stack[top]
    if output is not None:
        stack[top] = output


def top(stack: list[IROperand]) -> IROperand:
    top_idx = len(stack) - 1
    return stack[top_idx]


def position(stack: list[IROperand], op: IROperand) -> int | None:
    top = len(stack) - 1
    for i, item in enumerate(stack):
        pos = top - i
        if item == op:
            return pos

    return None


def op_reorder(stack: list[IROperand], ops: list[IROperand]) -> list[IROperand]:
    needed: list[IROperand] = []
    for op in reversed(ops):
        if op not in stack:
            needed.append(op)
            stack.insert(0, op)
    for i, op in reversed(list(enumerate(reversed(ops)))):
        assert op in stack
        op_position = position(stack, op)
        assert op_position is not None, f"operand is not in stack {op}, {stack}"

        # assert isinstance(op, IRVariable), f"operand must be variable got {op}"
        swap(stack, op_position)
        swap(stack, i)
    return needed


def max_same_prefix(stack_a: list[IROperand], stack_b: list[IROperand]) -> list[IROperand]:
    res = []
    for a, b in zip(stack_a, stack_b):
        if a != b:
            break
        res.append(a)
    # print(res)
    return res


class StoreType(Enum):
    PUSH = 1
    SWAP = 2
    DUP = 3


# this wont be part of the analysis framework
class StackOrder:
    bb_to_stack: dict[IRBasicBlock, list[IROperand]]
    liveness: LivenessAnalysis
    store_to_type: dict[IRInstruction, StoreType]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        self.analyses_cache = analyses_cache
        self.function = function
        self.store_to_type = dict()
        self.liveness = self.analyses_cache.request_analysis(LivenessAnalysis)

    def calculates_store_types(self):
        self.store_to_type = dict()
        for bb in self.function.get_basic_blocks():
            self._handle_bb_store_types(bb)

    def handle_bb(self, bb: IRBasicBlock) -> list[IROperand]:
        stack: list[IROperand] = []
        needed: list[IROperand] = []

        for inst in bb.instructions:
            if inst.opcode == "store":
                self._handle_store(inst, stack, needed)
            else:
                if inst.opcode == "phi":
                    ops = [op for _, op in inst.phi_operands]
                elif inst.is_bb_terminator:
                    ops = [op for op in inst.operands if not isinstance(op, IRLabel)]
                else:
                    ops = inst.operands

                inst_needed = op_reorder(stack, ops)
                needed.extend(inst_needed)
                if len(ops) > 0:
                    stack_top = list(stack[-len(ops) :])
                    assert (
                        ops == stack_top
                    ), f"the top of the stack is not correct, {ops}, {stack_top}"

                    stack = stack[0 : -len(ops)]

                output = inst.output
                if output is not None:
                    stack.append(output)

        return list(reversed(needed))

    def handle_bbs(self, bbs: list[IRBasicBlock]) -> list[IROperand]:
        if len(bbs) == 0:
            return []
        res = self.handle_bb(bbs[0])
        for bb in bbs[1:]:
            tmp = self.handle_bb(bb)
            res = max_same_prefix(res, tmp)
        return res

    def _handle_store(self, inst: IRInstruction, stack: list[IROperand], needed: list[IROperand]):
        assert inst.opcode == "store"
        ops = inst.operands
        assert len(ops) == 1
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
                op_position = position(stack, op)
                assert op_position is not None
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
            if isinstance(op, (IRLiteral, IRLabel)):
                self.store_to_type[inst] = StoreType.PUSH
                continue

            assert isinstance(op, IRVariable)
            next_liveness = self.liveness.live_vars_at(bb.instructions[i + 1])
            if op in next_liveness:
                self.store_to_type[inst] = StoreType.DUP
            else:
                self.store_to_type[inst] = StoreType.SWAP
