from enum import Enum

from vyper.venom.analysis import CFGAnalysis, LivenessAnalysis
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
from collections import deque, defaultdict




def _max_same_prefix(stack_a: list[IROperand], stack_b: list[IROperand]) -> list[IROperand]:
    res = []
    for a, b in zip(stack_a, stack_b):
        if a != b:
            break
        res.append(a)
    return res


class StoreType(Enum):
    PUSH = 1
    SWAP = 2
    DUP = 3

class Stack:
    data: list[IROperand]

    def __init__(self):
        self.data = []
    
    def __repr__(self) -> str:
        return repr(self.data)

    def _swap(self, position: int, output: IROperand | None = None):
        top = len(self.data) - 1
        position = top - position
        if position == top:
            if output is not None:
                self.data[top] = output
            return
        self.data[top], self.data[position] = self.data[position], self.data[top]
        if output is not None:
            self.data[top] = output


    def _position(self, op: IROperand) -> int | None:
        top = len(self.data) - 1
        for i, item in enumerate(self.data):
            pos = top - i
            if item == op:
                return pos

        return None


    def _op_reorder(self, ops: list[IROperand]) -> list[IROperand]:
        needed: list[IROperand] = []
        for op in reversed(ops):
            if op not in self.data:
                if op not in needed:
                    needed.append(op)
                self.data.insert(0, op)
        for i, op in reversed(list(enumerate(reversed(ops)))):
            assert op in self.data
            op_position = self._position(op)
            assert op_position is not None, f"operand is not in stack {op}, {self.data}"

            self._swap(op_position)
            self._swap(i)
        return list(reversed(needed))



# this wont be part of the analysis framework
class StackOrder:
    from_to_stack: dict[tuple[IRBasicBlock, IRBasicBlock], list[IROperand]]
    bb_to_stack: dict[IRBasicBlock, list[IROperand]]
    liveness: LivenessAnalysis
    store_to_type: dict[IRInstruction, StoreType]

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        self.analyses_cache = analyses_cache
        self.function = function
        self.store_to_type = dict()
        self.bb_to_stack = dict()
        self.from_to_stack = dict()
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.liveness = self.analyses_cache.request_analysis(LivenessAnalysis)

    def calculates_store_types(self):
        self.store_to_type = dict()
        for bb in self.function.get_basic_blocks():
            self._handle_bb_store_types(bb)

    def calculate_all_orders(self):
        self.calculates_store_types()
        worklist = deque(self.cfg.dfs_post_walk)
        last_stack_orders: dict[IRBasicBlock, list] = dict()

        while len(worklist) > 0:
            bb = worklist.popleft()
            stack_order = self.get_prefered_stack(bb, list(self.cfg.cfg_out(bb)))
            if bb in last_stack_orders and stack_order == last_stack_orders[bb]:
                continue
            last_stack_orders[bb] = stack_order
            for inbb in self.cfg.cfg_in(bb):
                worklist.append(inbb)


    def _handle_bb(self, bb: IRBasicBlock) -> list[IROperand]:
        stack: Stack = Stack()
        needed: list[IROperand] = []
        phis: set[IRVariable] = set()
        # from bb we need this var and it is rewriten to that var
        phi_renames: dict[IRLabel, list[tuple[IRVariable, IRVariable, IRInstruction]]] = defaultdict(list)
        phi_positions: dict[IRVariable, int] = dict()

        for inst in bb.instructions:
            if inst.opcode == "assign":
                inst_needed = self._handle_store(inst, stack)
            elif inst.opcode == "phi":
                inst_needed = self._handle_phi(inst, phis, phi_renames)
            else:
                inst_needed = self._handle_other_inst(inst, stack)

            for op in inst_needed:
                if op not in needed:
                    if op in phis:
                        assert op not in phi_positions
                        assert isinstance(op, IRVariable)
                        phi_positions[op] = len(needed)
                    needed.append(op)
        

        for pred in self.cfg.cfg_in(bb):
            assert isinstance(pred, IRBasicBlock) # help mypy
            transition = needed.copy()
            removed = 0
            added = []
            for var, phi_var, inst in phi_renames[pred.label]:
                assert var in self.liveness.out_vars(pred), f"{var} not life at {pred}, {inst}, {bb}, {self.liveness.out_vars(pred)}"
                if phi_var not in phi_positions:
                    added.append(var)
                    continue
                #assert phi_var in phi_positions, f"phi var not in phi positions {phi_var}, {phi_positions}, {bb}"
                pos = phi_positions[phi_var] - removed
                if var in transition:
                    del transition[pos]
                    removed += 1
                    continue

                assert transition[pos] == phi_var
                transition[pos] = var
            transition = added + transition
            self.from_to_stack[(pred, bb)] = transition


        self.bb_to_stack[bb] = needed
        return needed

    # compute max prefix for all the orders of the
    # succesor basicblocks
    def _merge(self, orders: list[list[IROperand]]) -> list[IROperand]:
        if len(orders) == 0:
            return []
        res: list[IROperand] = orders[0].copy()
        for order in orders:
            res = _max_same_prefix(res, order)
        return res

    def get_prefered_stack(self, origin: IRBasicBlock, succesors: list[IRBasicBlock]) -> list[IROperand]:
        for bb in succesors:
            self._handle_bb(bb)
        bb_orders = [self.from_to_stack[(origin, bb)] for bb in succesors]

        # reverse so it it is in the same order
        # as the operands for the easier handle
        # in dft pass (same logic as normal inst)
        return list(reversed(self._merge(bb_orders)))

    def _handle_store(self, inst: IRInstruction, stack: Stack) -> list[IROperand]:
        needed = []
        assert inst.opcode == "assign"
        ops = inst.operands
        assert len(ops) == 1
        op = ops[0]

        output = inst.output
        assert output is not None

        store_type = self.store_to_type[inst]
        if store_type == StoreType.PUSH:
            stack.data.append(output)
        elif store_type == StoreType.SWAP:
            op_position = stack._position(op)
            if op_position is None:
                stack.data.insert(0, op)
                #assert op not in needed, f"op {op} already in needed {needed} ({inst})"
                needed.append(op)
                op_position = stack._position(op)
                assert op_position is not None
            stack._swap(op_position, output)
        elif store_type == StoreType.DUP:
            stack.data.append(output)
            if op not in stack.data:
                needed.append(op)

        return needed
    
    def _handle_other_inst(self, inst: IRInstruction, stack: Stack) -> list[IROperand]:
        assert inst.opcode not in ("assign", "phi")
        bb = inst.parent
        if inst.is_bb_terminator:
            ops = [op for op in inst.operands if not isinstance(op, IRLabel)]
            out_bbs = self.cfg.cfg_out(bb)
            orders = [self.from_to_stack.get((bb, out_bb), []) for out_bb in out_bbs]
            tmp = self._merge(orders)
            for op in tmp:
                if op not in ops:
                    ops.append(op)
        elif inst.opcode == "log":
            # first opcode in log is magic
            ops = inst.operands[1:]
        elif inst.opcode == "offset":
            # offset ops are magic
            ops = []
        else:
            ops = inst.operands

        ops = [op for op in ops if not isinstance(op, IRLabel)]
        assert not any(isinstance(op, IRLiteral) for op in ops), inst
        inst_needed = stack._op_reorder(ops)

        if len(ops) > 0:
            stack_top = list(stack.data[-len(ops) :])
            assert (
                ops == stack_top
            ), f"the top of the stack is not correct, {ops}, {stack_top}"

            stack.data = stack.data[0 : -len(ops)]

        if inst.output is not None:
            stack.data.append(inst.output)

        return inst_needed

    def _handle_phi(self, inst: IRInstruction, phis: set[IRVariable], phi_renames) -> list[IROperand]:
        assert inst.opcode == "phi"
        assert inst.output is not None
        for label, op in inst.phi_operands:
            assert isinstance(op, IRVariable)
            # phi renames op -> inst.output
            phi_renames[label].append((op, inst.output, inst))
        #stack.append(inst.output)
        phis.add(inst.output)
        return []

    # compute what will store do in bytecode
    def _handle_bb_store_types(self, bb: IRBasicBlock):
        for i, inst in enumerate(bb.instructions):
            if inst.opcode != "assign":
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
