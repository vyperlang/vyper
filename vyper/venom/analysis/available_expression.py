from dataclasses import dataclass
from functools import cached_property

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

UNINTERESTING_OPCODES = ["store", "param", "offset", "phi", "nop"]
_NONIDEMPOTENT_INSTRUCTIONS = frozenset(["log", "call", "staticcall", "delegatecall", "invoke"])


@dataclass
class _Expression:
    first_inst: IRInstruction
    opcode: str
    operands: list["IROperand | _Expression"]
    ignore_msize: bool

    # equality for lattices only based on first_inst
    def __eq__(self, other) -> bool:
        if not isinstance(other, _Expression):
            return False

        return self.first_inst == other.first_inst

    # Full equality for expressions based on opcode and operands
    def same(self, other) -> bool:
        if type(self) is not type(other):
            return False

        if self.opcode != other.opcode:
            return False

        if self.first_inst == other.first_inst:
            return True

        # Early return special case for commutative instructions
        if self.is_commutative:
            if self.operands[0].same(other.operands[1]) and self.operands[1].same(
                other.operands[0]
            ):
                return True

        # General case
        for self_op, other_op in zip(self.operands, other.operands):
            if not self_op.same(other_op):
                return False

        return True

    def __hash__(self) -> int:
        return hash(self.first_inst)

    def __repr__(self) -> str:
        if self.opcode == "store":
            assert len(self.operands) == 1, "wrong store"
            return repr(self.operands[0])
        res = self.opcode + " [ "
        for op in self.operands:
            res += repr(op) + " "
        res += "]"
        return res

    @cached_property
    def get_depth(self) -> int:
        max_depth = 0
        for op in self.operands:
            if isinstance(op, _Expression):
                d = op.get_depth
                if d > max_depth:
                    max_depth = d
        return max_depth + 1

    @cached_property
    def get_reads(self) -> Effects:
        tmp_reads = self.first_inst.get_read_effects()
        for op in self.operands:
            if isinstance(op, _Expression):
                tmp_reads = tmp_reads | op.get_reads
        if self.ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads

    @cached_property
    def get_writes(self) -> Effects:
        tmp_reads = self.first_inst.get_write_effects()
        for op in self.operands:
            if isinstance(op, _Expression):
                tmp_reads = tmp_reads | op.get_writes
        if self.ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads

    @property
    def is_commutative(self) -> bool:
        return self.first_inst.is_commutative


class AvailableExpressionAnalysis(IRAnalysis):
    inst_to_expr: dict[IRInstruction, _Expression]
    dfg: DFGAnalysis
    inst_to_available: dict[IRInstruction, OrderedSet[_Expression]]
    bb_outs: dict[IRBasicBlock, OrderedSet[_Expression]]

    # the size of the expressions
    # that are considered in the analysis
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

        self.inst_to_expr = dict()
        self.inst_to_available = dict()
        self.bb_outs = dict()

        self.ignore_msize = not self._contains_msize()

    def analyze(self, min_depth: int = _MIN_DEPTH, max_depth: int = _MAX_DEPTH):
        self.min_depth = min_depth
        self.max_depth = max_depth

        worklist: OrderedSet = OrderedSet()
        worklist.add(self.function.entry)
        while len(worklist) > 0:
            bb: IRBasicBlock = worklist.pop()
            changed = self._handle_bb(bb)

            if changed:
                for out in bb.cfg_out:
                    worklist.add(out)

    # msize effect should be only necessery
    # to be handled when there is a possibility
    # of msize read otherwise it should not make difference
    # for this analysis
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
                *(self.bb_outs.get(in_bb, OrderedSet()) for in_bb in bb.cfg_in)
            )

        #bb_lat = self.lattice.data[bb]
        change = False
        for inst in bb.instructions:
            if inst.opcode in UNINTERESTING_OPCODES or inst.opcode in BB_TERMINATORS:
                continue

            if inst not in self.inst_to_available or available_expr != self.inst_to_available[inst]:
                self.inst_to_available[inst] = available_expr.copy()
            inst_expr = self.get_expression(inst, available_expr)
            write_effects = inst_expr.get_writes
            for expr in available_expr.copy():
                read_effects = expr.get_reads
                if read_effects & write_effects != EMPTY:
                    available_expr.remove(expr)
                    continue
                write_effects_expr = expr.get_writes
                if write_effects_expr & write_effects != EMPTY:
                    available_expr.remove(expr)

            if (
                inst_expr.get_depth in range(self.min_depth, self.max_depth + 1)
                and inst.opcode not in _NONIDEMPOTENT_INSTRUCTIONS
                and write_effects & inst_expr.get_reads == EMPTY
            ):
                available_expr.add(inst_expr)

        if bb not in self.bb_outs or available_expr != self.bb_outs[bb]:
            self.bb_outs[bb] = available_expr.copy()
            # change is only necessery when the output of the
            # basic block is changed (otherwise it wont affect rest)
            change |= True

        return change

    def _get_operand(
        self, op: IROperand, available_exprs: OrderedSet[_Expression], depth: int
    ) -> IROperand | _Expression:
        if depth > 0 and isinstance(op, IRVariable):
            inst = self.dfg.get_producing_instruction(op)
            assert inst is not None
            # this can both create better solutions and is necessery
            # for correct effect handle, otherwise you could go over
            # effect bounderies
            if inst.is_volatile:
                return op
            if inst in self.inst_to_expr:
                return self.inst_to_expr[inst]
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
        available_exprs = available_exprs or self.inst_to_available.get(inst, OrderedSet())
        depth = self.max_depth if depth is None else depth
        operands: list[IROperand | _Expression] = self._get_operands(inst, available_exprs, depth)
        expr = _Expression(inst, inst.opcode, operands, self.ignore_msize)

        if inst in self.inst_to_expr and self.inst_to_expr[inst] in available_exprs:
            return self.inst_to_expr[inst]

        for e in available_exprs:
            if expr.same(e):
                self.inst_to_expr[inst] = e
                return e

        self.inst_to_expr[inst] = expr
        return expr

    def get_available(self, inst: IRInstruction) -> OrderedSet[_Expression]:
        return self.inst_to_available.get(inst, OrderedSet())
