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
from vyper.venom.effects import reads as effect_reads
from vyper.venom.effects import writes as effect_write

NONIDEMPOTENT_INSTRUCTIONS = frozenset(["log", "call", "staticcall", "delegatecall", "invoke"])

# instructions that queries info about current
# environment this is done because we know that
# all these instruction should have always
# the same value in function
IMMUTABLE_ENV_QUERIES = frozenset(["calldatasize", "gaslimit", "address", "codesize"])


@dataclass(frozen=True)
class _Expression:
    inst: IRInstruction
    opcode: str
    # the child is either expression of operand since
    # there are possibilities for cycles
    operands: list["IROperand | _Expression"]
    ignore_msize: bool

    # equality for lattices only based on original instruction
    def __eq__(self, other) -> bool:
        if not isinstance(other, _Expression):
            return False

        if self.opcode in IMMUTABLE_ENV_QUERIES:
            return self.opcode == other.opcode

        return self.inst == other.inst

    def __hash__(self) -> int:
        if self.opcode in IMMUTABLE_ENV_QUERIES:
            return hash(self.opcode)
        return hash(self.inst)

    # Full equality for expressions based on opcode and operands
    def same(self, other) -> bool:
        return same(self, other)

    def __repr__(self) -> str:
        if self.opcode == "store":
            assert len(self.operands) == 1, "wrong store"
            return repr(self.operands[0])
        res = self.opcode + " [ "
        for op in self.operands:
            res += repr(op) + " "
        res += "]"
        res += f" {self.inst.output} {self.inst.parent.label}"
        return res

    @cached_property
    def depth(self) -> int:
        max_depth = 0
        for op in self.operands:
            if isinstance(op, _Expression):
                d = op.depth
                if d > max_depth:
                    max_depth = d
        return max_depth + 1


    def get_reads(self) -> Effects:
        tmp_reads = self.inst.get_read_effects()
        if self.ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads

    def get_writes(self) -> Effects:
        tmp_reads = self.inst.get_write_effects()
        if self.ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads

    @property
    def is_commutative(self) -> bool:
        return self.inst.is_commutative


def same(a: IROperand | _Expression, b: IROperand | _Expression) -> bool:
    if isinstance(a, IROperand) and isinstance(b, IROperand):
        return a.value == b.value
    if not isinstance(a, _Expression) or not isinstance(b, _Expression):
        return False

    if a is b:
        return True

    if a.opcode != b.opcode:
        return False

    # Early return special case for commutative instructions
    if a.is_commutative:
        if same(a.operands[0], b.operands[1]) and same(a.operands[1], b.operands[0]):
            return True

    # General case
    for self_op, other_op in zip(a.operands, b.operands):
        if self_op != other_op:
            return False

    return True


class _AvailableExpression:
    """
    Class that holds available expression
    and provides API for handling them
    """

    buckets: dict[str, OrderedSet[_Expression]]

    def __init__(self):
        self.buckets = dict()

    def __eq__(self, other) -> bool:
        if not isinstance(other, _AvailableExpression):
            return False

        return self.buckets == other.buckets

    def __repr__(self) -> str:
        res = "available expr\n"
        for key, val in self.buckets.items():
            res += f"\t{key}: {val}\n"
        return res

    def diff(self, other: "_AvailableExpression"):
        if self.buckets.keys() != other.buckets.keys():
            print("-", set(set(self.buckets.keys()).difference(set(other.buckets.keys()))))
            print("+", set(set(other.buckets.keys()).difference(set(self.buckets.keys()))))
            return
        for key in self.buckets.keys():
            if self.buckets[key] != other.buckets[key]:
                a = self.buckets[key]
                b = other.buckets[key]
                print("-", a.difference(b))
                print("+", b.difference(a))


    def add(self, expr: _Expression):
        if expr.opcode not in self.buckets:
            self.buckets[expr.opcode] = OrderedSet()

        self.buckets[expr.opcode].add(expr)

    def remove_effect(self, effect: Effects):
        if effect == EMPTY:
            return
        to_remove = set()
        for opcode in self.buckets.keys():
            op_effect = effect_reads.get(opcode, EMPTY) | effect_write.get(opcode, EMPTY)
            if op_effect & effect != EMPTY:
                to_remove.add(opcode)

        for opcode in to_remove:
            del self.buckets[opcode]

    def get_same(self, expr: _Expression) -> _Expression | None:
        if expr.opcode not in self.buckets:
            return None
        bucket = self.buckets[expr.opcode]

        for e in bucket:
            if expr.same(e):
                return e

        return None

    def copy(self) -> "_AvailableExpression":
        res = _AvailableExpression()
        for key, val in self.buckets.items():
            res.buckets[key] = val.copy()
        return res

    @staticmethod
    def intersection(*others: "_AvailableExpression | None"):
        tmp = list(o for o in others if o is not None)
        if len(tmp) == 0:
            return _AvailableExpression()
        res = tmp[0].copy()
        for item in tmp[1:]:
            buckets = res.buckets.keys() & item.buckets.keys()
            tmp_res = res
            res = _AvailableExpression()
            for bucket in buckets:
                res.buckets[bucket] = OrderedSet.intersection(
                    tmp_res.buckets[bucket], item.buckets[bucket]
                )  # type: ignore
        return res


class CSEAnalysis(IRAnalysis):
    inst_to_expr: dict[IRInstruction, _Expression]
    dfg: DFGAnalysis
    inst_to_available: dict[IRInstruction, _AvailableExpression]
    bb_ins: dict[IRBasicBlock, _AvailableExpression]
    bb_outs: dict[IRBasicBlock, _AvailableExpression]
    eq_vars: VarEquivalenceAnalysis

    ignore_msize: bool

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        assert isinstance(dfg, DFGAnalysis)
        self.dfg = dfg
        self.eq_vars = self.analyses_cache.request_analysis(VarEquivalenceAnalysis)  # type: ignore

        self.inst_to_expr = dict()
        self.inst_to_available = dict()
        self.bb_ins = dict()
        self.bb_outs = dict()

        self.ignore_msize = not self._contains_msize()

    def analyze(self):
        from collections import deque
        worklist = deque()
        worklist.append(self.function.entry)
        while len(worklist) > 0:
            bb: IRBasicBlock = worklist.popleft()
            if self._handle_bb(bb):
                worklist.extend(bb.cfg_out)

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
        available_expr: _AvailableExpression = _AvailableExpression.intersection(
            *(self.bb_outs.get(out_bb, _AvailableExpression()) for out_bb in bb.cfg_in)
        )

        if bb in self.bb_ins and self.bb_ins[bb] == available_expr:
            return False

        self.bb_ins[bb] = available_expr.copy()

        change = False
        for inst in bb.instructions:
            if inst.opcode in ("store", "phi") or inst.opcode in BB_TERMINATORS:
                continue

            if inst not in self.inst_to_available or available_expr != self.inst_to_available[inst]:
                self.inst_to_available[inst] = available_expr.copy()

            expr = self._get_expression(inst, available_expr)
            write_effects = expr.get_writes()
            available_expr.remove_effect(write_effects)

            # nonidempotent instruction effect other instructions
            # but since it cannot be substituted it does not have
            # to be added to available exprs
            if inst.opcode in NONIDEMPOTENT_INSTRUCTIONS:
                continue

            if expr.get_writes() & expr.get_reads() == EMPTY:
                available_expr.add(expr)

        if bb not in self.bb_outs or available_expr != self.bb_outs[bb]:
            self.bb_outs[bb] = available_expr
            # change is only necessery when the output of the
            # basic block is changed (otherwise it wont affect rest)
            change |= True

        return change

    def _get_operand(
        self, op: IROperand, available_exprs: _AvailableExpression
    ) -> IROperand | _Expression:
        if isinstance(op, IRVariable):
            inst = self.dfg.get_producing_instruction(op)
            assert inst is not None
            # the phi condition is here because it is only way to
            # create dataflow loop
            if inst.opcode == "phi":
                return op
            if inst.opcode == "store":
                return self._get_operand(inst.operands[0], available_exprs)
            if inst in self.inst_to_expr:
                return self.inst_to_expr[inst]
            return self._get_expression(inst, available_exprs)
        return op

    def get_expression(
        self, inst: IRInstruction, available_exprs: _AvailableExpression | None = None
    ) -> _Expression:
        available_exprs = available_exprs or self.inst_to_available.get(
            inst, _AvailableExpression()
        )

        assert available_exprs is not None  # help mypy
        return self._get_expression(inst, available_exprs)

    def _get_expression(self, inst: IRInstruction, available_exprs: _AvailableExpression):
        if inst.opcode in IMMUTABLE_ENV_QUERIES:
            return _Expression(inst, inst.opcode, [], self.ignore_msize)

        # create expression
        operands: list[IROperand | _Expression] = [
            self._get_operand(op, available_exprs) for op in inst.operands
        ]
        expr = _Expression(inst, inst.opcode, operands, self.ignore_msize)

        same_expr = available_exprs.get_same(expr)
        if same_expr is not None:
            self.inst_to_expr[inst] = same_expr
            return same_expr

        self.inst_to_expr[inst] = expr
        return expr
