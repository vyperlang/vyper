from collections import deque
from dataclasses import dataclass

from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysesCache, IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.basicblock import (
    BB_TERMINATORS,
    IRBasicBlock,
    IRInstruction,
    IROperand,
    IRVariable,
)
from vyper.venom.context import IRFunction
from vyper.venom.effects import EMPTY, Effects

_MAX_DEPTH = 5
_MIN_DEPTH = 2


@dataclass
class _Expression:
    first_inst: IRInstruction
    opcode: str
    operands: list["IROperand | _Expression"]

    def __eq__(self, other):
        if not isinstance(other, _Expression):
            return False
        return self.first_inst == other.first_inst

    def __hash__(self) -> int:
        return hash((self.opcode, *self.operands))

    def __repr__(self) -> str:
        if self.opcode == "store":
            assert len(self.operands) == 1, "wrong store"
            return repr(self.operands[0])
        res = self.opcode + " [ "
        for op in self.operands:
            res += repr(op) + " "
        res += "]"
        return res

    def same(self, other: "_Expression") -> bool:
        if self.opcode != other.opcode:
            return False
        for self_op, other_op in zip(self.operands, other.operands):
            if type(self_op) is not type(other_op):
                return False
            if isinstance(self_op, _Expression):
                assert isinstance(other_op, _Expression)
                if not self_op.same(other_op):
                    return False
            else:
                assert isinstance(self_op, IROperand)
                assert isinstance(other_op, IROperand)
                if self_op != other_op:
                    return False
        return True

    def contains_expr(self, expr: "_Expression") -> bool:
        for op in self.operands:
            if op == expr:
                return True
            if isinstance(op, _Expression) and op.contains_expr(expr):
                return True
        return False

    def get_depth(self) -> int:
        max_depth = 0
        for op in self.operands:
            if isinstance(op, _Expression):
                d = op.get_depth()
                if d > max_depth:
                    max_depth = d
        return max_depth + 1

    def get_reads(self, ignore_msize: bool) -> Effects:
        tmp_reads = self.first_inst.get_read_effects()
        for op in self.operands:
            if isinstance(op, _Expression):
                tmp_reads = tmp_reads | op.get_reads(ignore_msize)
        if ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads

    def get_writes(self, ignore_msize: bool) -> Effects:
        tmp_reads = self.first_inst.get_write_effects()
        for op in self.operands:
            if isinstance(op, _Expression):
                tmp_reads = tmp_reads | op.get_writes(ignore_msize)
        if ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads


class _BBLattice:
    data: dict[IRInstruction, OrderedSet[_Expression]]
    out: OrderedSet[_Expression]
    in_cache: OrderedSet[_Expression] | None

    def __init__(self, bb: IRBasicBlock):
        self.data = dict()
        self.out = OrderedSet()
        self.in_cache = None
        for inst in bb.instructions:
            self.data[inst] = OrderedSet()


_UNINTERESTING_OPCODES = ["store", "param", "offset", "phi", "nop"]


class _FunctionLattice:
    data: dict[IRBasicBlock, _BBLattice]

    def __init__(self, function: IRFunction):
        self.data = dict()
        for bb in function.get_basic_blocks():
            self.data[bb] = _BBLattice(bb)


class AvailableExpressionAnalysis(IRAnalysis):
    expressions: OrderedSet[_Expression] = OrderedSet()
    inst_to_expr: dict[IRInstruction, _Expression] = dict()
    dfg: DFGAnalysis
    lattice: _FunctionLattice
    min_depth: int
    max_depth: int
    ignore_msize: bool

    def __init__(
        self,
        analyses_cache: IRAnalysesCache,
        function: IRFunction,
        min_depth: int = _MIN_DEPTH,
        max_depth: int = _MAX_DEPTH,
    ):
        super().__init__(analyses_cache, function)
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        assert isinstance(dfg, DFGAnalysis)
        self.dfg = dfg

        self.min_depth = min_depth
        self.max_depth = max_depth

        self.lattice = _FunctionLattice(function)

        self.ignore_msize = not self._contains_msize()

    def analyze(self, min_depth: int = _MIN_DEPTH, max_depth: int = _MAX_DEPTH):
        self.min_depth = min_depth
        self.max_depth = max_depth
        worklist: deque = deque()
        worklist.append(self.function.entry)
        while len(worklist) > 0:
            bb: IRBasicBlock = worklist.popleft()
            changed = self._handle_bb(bb)

            if changed:
                for out in bb.cfg_out:
                    if out not in worklist:
                        worklist.append(out)

    def _contains_msize(self) -> bool:
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "msize":
                    return True
        return False

    def _handle_bb(self, bb: IRBasicBlock) -> bool:
        available_expr: OrderedSet[_Expression] = OrderedSet()
        if len(bb.cfg_in) > 0:
            available_expr = OrderedSet.intersection(
                *(self.lattice.data[in_bb].out for in_bb in bb.cfg_in)
            )

        bb_lat = self.lattice.data[bb]
        if bb_lat.in_cache is not None and available_expr == bb_lat.in_cache:
            return False
        bb_lat.in_cache = available_expr
        change = False
        for inst in bb.instructions:
            if inst.opcode in _UNINTERESTING_OPCODES or inst.opcode in BB_TERMINATORS:
                continue
            if available_expr != bb_lat.data[inst]:
                bb_lat.data[inst] = available_expr.copy()
                change |= True

            inst_expr = self.get_expression(inst, available_expr)
            # write_effects = inst.get_write_effects()  # writes.get(inst_expr.opcode, ())
            write_effects = inst_expr.get_writes(self.ignore_msize)
            for expr in available_expr.copy():
                read_effects = expr.get_reads(self.ignore_msize)
                if read_effects & write_effects != EMPTY:
                    available_expr.remove(expr)
                    continue
                write_effects_expr = expr.get_writes(self.ignore_msize)
                if write_effects_expr & write_effects != EMPTY:
                    available_expr.remove(expr)

            if (
                inst_expr.get_depth() in range(self.min_depth, self.max_depth + 1)
                and write_effects & inst_expr.get_reads(self.ignore_msize) == EMPTY
            ):
                available_expr.add(inst_expr)

        if available_expr != bb_lat.out:
            bb_lat.out = available_expr.copy()
            change |= True

        return change

    def _get_operand(
        self, op: IROperand, available_exprs: OrderedSet[_Expression], depth: int
    ) -> IROperand | _Expression:
        if depth > 0 and isinstance(op, IRVariable):
            inst = self.dfg.get_producing_instruction(op)
            assert inst is not None
            if not inst.is_volatile:
                return self.get_expression(inst, available_exprs, depth - 1)
        return op

    def _get_operands(
        self, inst: IRInstruction, available_exprs: OrderedSet[_Expression], depth: int
    ) -> list[IROperand | _Expression]:
        return [self._get_operand(op, available_exprs, depth) for op in inst.operands]

    def get_expression(
        self,
        inst: IRInstruction,
        available_exprs: OrderedSet[_Expression] | None = None,
        depth: int | None = None,
    ) -> _Expression:
        if available_exprs is None:
            available_exprs = self.lattice.data[inst.parent].data[inst]
        if depth is None:
            depth = self.max_depth
        operands: list[IROperand | _Expression] = self._get_operands(inst, available_exprs, depth)
        expr = _Expression(inst, inst.opcode, operands)
        for e in available_exprs:
            if expr.same(e):
                return e

        return expr

    def get_available(self, inst: IRInstruction) -> OrderedSet[_Expression]:
        return self.lattice.data[inst.parent].data[inst]
