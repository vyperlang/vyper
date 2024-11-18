# REVIEW: rename this to cse_analysis or common_subexpression_analysis

from dataclasses import dataclass
from functools import cached_property

from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysesCache, IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.equivalent_vars import VarEquivalenceAnalysis
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

UNINTERESTING_OPCODES = [
    "store",
    "param",
    "offset",
    "phi",
    "nop",
    "calldatasize",
    "returndatasize",
    "gas",
]
_NONIDEMPOTENT_INSTRUCTIONS = frozenset(["log", "call", "staticcall", "delegatecall", "invoke"])


@dataclass
class _Expression:
    inst: IRInstruction
    opcode: str
    # REVIEW: bad type: this list only contains _Expressions, otherwise
    # we could not call same(self_op, other_op) in the recursion.
    operands: list["IROperand | _Expression"]
    ignore_msize: bool

    # equality for lattices only based on original instruction
    def __eq__(self, other) -> bool:
        if not isinstance(other, _Expression):
            return False

        return self.inst == other.inst

    def __hash__(self) -> int:
        return hash(self.inst)

    # Full equality for expressions based on opcode and operands
    # REVIEW: this is inefficient. we do not need to do the recursion if
    # we do a shallow comparison - we can check `self_op is other_op` for
    # in the loop over zip(self.operands, other.operands). because of
    # how expressions are computed, we are guaranteed uniqueness of expressions
    # in available_expressions
    def same(self, other, eq_vars: VarEquivalenceAnalysis) -> bool:
        return same(self, other, eq_vars)

    def __repr__(self) -> str:
        if False and self.opcode == "store":
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
    def get_reads_deep(self) -> Effects:
        tmp_reads = self.inst.get_read_effects()
        for op in self.operands:
            if isinstance(op, _Expression):
                tmp_reads = tmp_reads | op.get_reads
        if self.ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads

    @cached_property
    def get_reads(self) -> Effects:
        tmp_reads = self.inst.get_read_effects()
        if self.ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads

    @cached_property
    def get_writes_deep(self) -> Effects:
        tmp_reads = self.inst.get_write_effects()
        for op in self.operands:
            if isinstance(op, _Expression):
                tmp_reads = tmp_reads | op.get_writes
        if self.ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads

    @cached_property
    def get_writes(self) -> Effects:
        tmp_reads = self.inst.get_write_effects()
        if self.ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads

    @property
    def is_commutative(self) -> bool:
        return self.inst.is_commutative


def same(
    a: IROperand | _Expression, b: IROperand | _Expression, eq_vars: VarEquivalenceAnalysis
) -> bool:
    if isinstance(a, IROperand) and isinstance(b, IROperand):
        return a.value == b.value
    if not isinstance(a, _Expression) or not isinstance(b, _Expression):
        return False

    if a.opcode != b.opcode:
        return False

    if a.inst == b.inst:
        return True

    # Early return special case for commutative instructions
    if a.is_commutative:
        if same(a.operands[0], b.operands[1], eq_vars) and same(
            a.operands[1], b.operands[0], eq_vars
        ):
            return True

    # General case
    for self_op, other_op in zip(a.operands, b.operands):
        if (
            self_op is not other_op
            and not eq_vars.equivalent(self_op, other_op)
            and self_op != other_op
        ):
            return False

    return True


class CSEAnalysis(IRAnalysis):
    inst_to_expr: dict[IRInstruction, _Expression]
    dfg: DFGAnalysis
    inst_to_available: dict[IRInstruction, OrderedSet[_Expression]]
    bb_outs: dict[IRBasicBlock, OrderedSet[_Expression]]
    eq_vars: VarEquivalenceAnalysis

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
        self.eq_vars = self.analyses_cache.request_analysis(VarEquivalenceAnalysis)  # type: ignore

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

        # bb_lat = self.lattice.data[bb]
        change = False
        for inst in bb.instructions:
            # if inst.opcode in UNINTERESTING_OPCODES or inst.opcode in BB_TERMINATORS:
            if inst.opcode in BB_TERMINATORS:
                continue

            # REVIEW: why replace inst_to_available if they are not equal?
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

            if inst_expr.get_writes_deep & inst_expr.get_reads_deep == EMPTY:
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
        if isinstance(op, IRVariable):
            inst = self.dfg.get_producing_instruction(op)
            assert inst is not None
            # this can both create better solutions and is necessery
            # for correct effect handle, otherwise you could go over
            # effect bounderies
            if inst.is_volatile or inst.opcode == "phi":
                return op
            if inst.opcode == "store":
                return self._get_operand(inst.operands[0], available_exprs, depth - 1)
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
        assert available_exprs is not None
        depth = self.max_depth if depth is None else depth
        operands: list[IROperand | _Expression] = self._get_operands(inst, available_exprs, depth)
        expr = _Expression(inst, inst.opcode, operands, self.ignore_msize)

        if inst in self.inst_to_expr and self.inst_to_expr[inst] in available_exprs:
            return self.inst_to_expr[inst]

        def cond() -> bool:
            return False
            return (
                inst.opcode == "add"
                and isinstance(inst.operands[0], IRVariable)
                and inst.operands[0].value == "%13:3"
            )

        # REVIEW: performance issue - loop over available_exprs.
        for e in available_exprs:
            if expr.same(e, self.eq_vars):
                self.inst_to_expr[inst] = e
                return e

        self.inst_to_expr[inst] = expr
        return expr

    def get_available(self, inst: IRInstruction) -> OrderedSet[_Expression]:
        return self.inst_to_available.get(inst, OrderedSet())
