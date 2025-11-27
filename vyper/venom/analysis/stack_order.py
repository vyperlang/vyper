from vyper.venom.analysis import CFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IROperand, IRVariable
from vyper.venom.function import IRFunction

# needed [top, ... , bottom]
Needed = list[IRVariable]

Stack = list[IROperand]


def _swap(stack: Stack, op: IROperand):
    top = len(stack) - 1
    index = None
    for i, item in reversed(list(enumerate(stack))):
        if item == op:
            index = i

    assert index is not None

    stack[index], stack[top] = stack[top], stack[index]


def _swap_to(stack: Stack, depth: int):
    top = len(stack) - 1
    index = top - depth

    stack[index], stack[top] = stack[top], stack[index]


def _max_same_prefix(stack_a: Needed, stack_b: Needed):
    res: Needed = []
    for a, b in zip(stack_a, stack_b):
        if a != b:
            break
        res.append(a)
    return res


class StackOrderAnalysis:
    function: IRFunction
    liveness: LivenessAnalysis
    cfg: CFGAnalysis
    _from_to: dict[tuple[IRBasicBlock, IRBasicBlock], Needed]

    def __init__(self, ac: IRAnalysesCache):
        self._from_to = dict()
        self.ac = ac
        self.liveness = ac.request_analysis(LivenessAnalysis)
        self.cfg = ac.request_analysis(CFGAnalysis)

    def analyze_bb(self, bb: IRBasicBlock) -> Needed:
        self.needed: Needed = []
        self.stack: Stack = []

        for inst in bb.instructions:
            if inst.opcode == "assign":
                self._handle_assign(inst)
            elif inst.opcode == "phi":
                self._handle_inst(inst)
            elif inst.is_bb_terminator:
                self._handle_terminator(inst)
            else:
                self._handle_inst(inst)

            if len(inst.operands) > 0:
                if not inst.is_bb_terminator:
                    assert self.stack[-len(inst.operands) :] == inst.operands, (
                        inst,
                        self.stack,
                        inst.operands,
                    )
                self.stack = self.stack[: -len(inst.operands)]
            self.stack.extend(inst.get_outputs())

        for pred in self.cfg.cfg_in(bb):
            self._from_to[(pred, bb)] = self.needed.copy()

        return self.needed

    def get_stack(self, bb: IRBasicBlock) -> Needed:
        succs = self.cfg.cfg_out(bb)
        for succ in succs:
            self.analyze_bb(succ)
        orders = [self._from_to.get((bb, succ), []) for succ in succs]
        return self._merge(orders)

    def from_to(self, origin: IRBasicBlock, successor: IRBasicBlock) -> Needed:
        target = self._from_to.get((origin, successor), []).copy()

        for var in self.liveness.input_vars_from(origin, successor):
            if var not in target:
                target.append(var)

        return target

    def _handle_assign(self, inst: IRInstruction):
        assert inst.opcode == "assign"
        _ = inst.output  # Assert single output

        index = inst.parent.instructions.index(inst)
        next_inst = inst.parent.instructions[index + 1]
        next_live = self.liveness.live_vars_at(next_inst)

        src = inst.operands[0]

        if not isinstance(src, IRVariable):
            self.stack.append(src)
        elif src in next_live:
            self.stack.append(src)
            assert src in self.stack
            self._add_needed(src)
        else:
            if src not in self.stack:
                self.stack.append(src)
                self._add_needed(src)
            else:
                _swap(self.stack, src)

    def _add_needed(self, op: IRVariable):
        if op not in self.needed:
            self.needed.append(op)

    def _reorder(self, target_stack: Stack):
        count = len(target_stack)

        for index, op in enumerate(target_stack):
            depth = count - index - 1
            _swap(self.stack, op)
            _swap_to(self.stack, depth)

        if len(target_stack) != 0:
            assert target_stack == self.stack[-len(target_stack) :], (target_stack, self.stack)

    def _handle_inst(self, inst: IRInstruction):
        ops = inst.operands
        for op in ops:
            if isinstance(op, IRVariable) and op not in self.stack:
                self._add_needed(op)
            if op not in self.stack:
                self.stack.append(op)
        self._reorder(ops)

    def _merge(self, orders: list[Needed]) -> Needed:
        if len(orders) == 0:
            return []
        res = orders[0]
        for order in orders:
            res = _max_same_prefix(res, order)
        return res

    def _handle_terminator(self, inst: IRInstruction):
        bb = inst.parent
        orders = [self._from_to.get((bb, succ), []) for succ in self.cfg.cfg_out(bb)]
        ops = (op for op in inst.operands if isinstance(op, IRVariable))
        for op in ops:
            if op not in self.stack:
                self._add_needed(op)
        for op in self._merge(orders):
            if op not in self.stack:
                self._add_needed(op)
