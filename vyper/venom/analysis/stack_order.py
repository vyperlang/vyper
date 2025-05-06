from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.basicblock import IRBasicBlock, IROperand, IRVariable
from vyper.utils import OrderedSet, CompilerPanic
from vyper.venom.analysis import LivenessAnalysis


def swap(stack: list[IROperand], position: int):
    if position == 0:
        return
    top = len(stack) - 1
    stack[top], stack[position] = stack[position], stack[top]

def position(stack: list[IROperand], op: IROperand):
    top = len(stack) - 1
    for i, item in enumerate(reversed(stack)):
        pos = top - i
        if item == op:
            return pos

    raise CompilerPanic("item not in the stack")

def ops_order(stack: list[IROperand], needed: list[IROperand], next_liveness: OrderedSet[IRVariable]) -> tuple[list[IROperand], list[IROperand]]:
    added: list[IROperand] = []
    # we will have to dup these either way
    for op in needed:
        if op in next_liveness:
            stack.append(op)
    # pad stack with unknown
    diff_count = len(needed) > len(stack)
    if diff_count > 0:
        stack = needed[0:diff_count] + stack
        added = needed[0:diff_count]

    for op in needed:
        if op not in stack:
            stack.insert(0, op)
            added.insert(0, op)

    for i, op in enumerate(needed):
        pos = len(needed) - i - 1
        if op in next_liveness:
            stack.append(op)
            swap(stack, pos)
            continue
        if op == stack[pos]:
            continue
        current_pos = position(stack, op)
        swap(stack, current_pos)
        swap(stack, pos)
        

    return stack, added

class StackOrder(IRAnalysis):
    bb_to_stack: dict[IRBasicBlock, list[IROperand]]
    liveness: LivenessAnalysis

    def analyze(self):
        self.bb_to_stack = dict()
        self.liveness = self.analyses_cache.request_analysis(LivenessAnalysis)
        for bb in self.function.get_basic_blocks():
            self.bb_to_stack[bb] = self._handle_bb(bb)

    def _handle_bb(self, bb: IRBasicBlock) -> list[IROperand]: 
        stack: list[IROperand] = []
        needed: list[IROperand] = []

        for i, inst in enumerate(bb.instructions):
            print(inst)
            print(stack)
            ops = inst.operands
            if inst.is_bb_terminator:
                next_liveness = self.liveness.out_vars(inst.parent)
            else:
                next_inst = inst.parent.instructions[i + 1]
                next_liveness = self.liveness.inst_to_liveness[next_inst]
            stack, added = ops_order(stack, ops, next_liveness)
            print(stack)
            needed = added + needed
            assert stack[-len(ops):] == ops, (stack, ops)
            stack = stack[0:(-len(ops))]
            if inst.output is not None:
                stack.append(inst.output)

        return needed


