from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from functools import cached_property, lru_cache

import immutables

import vyper.venom.effects as effects
from vyper.venom.analysis.analysis import IRAnalysesCache, IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.basicblock import (
    COMMUTATIVE_INSTRUCTIONS,
    IRBasicBlock,
    IRInstruction,
    IROperand,
    IRVariable,
)
from vyper.venom.context import IRFunction
from vyper.venom.effects import Effects

SYS_EFFECTS = effects.LOG | effects.BALANCE | effects.EXTCODE

_nonidempotent_insts = []
for opcode, eff in effects.writes.items():
    if eff & SYS_EFFECTS != effects.EMPTY:
        _nonidempotent_insts.append(opcode)
# staticcall doesn't have external effects, but it is not idempotent since
# it can depend on gas
_nonidempotent_insts.append("staticcall")

NONIDEMPOTENT_INSTRUCTIONS = frozenset(_nonidempotent_insts)

# sanity
for opcode in ("call", "create", "staticcall", "delegatecall", "create2"):
    assert opcode in NONIDEMPOTENT_INSTRUCTIONS


# flag bitwise operations are somehow a perf bottleneck, cache them
@lru_cache
def _get_read_effects(opcode, ignore_msize):
    ret = effects.reads.get(opcode, effects.EMPTY)
    if ignore_msize:
        ret &= ~Effects.MSIZE
    return ret


@lru_cache
def _get_write_effects(opcode, ignore_msize):
    ret = effects.writes.get(opcode, effects.EMPTY)
    if ignore_msize:
        ret &= ~Effects.MSIZE
    return ret


@lru_cache
def _get_overlap_effects(opcode, ignore_msize):
    return _get_read_effects(opcode, ignore_msize) & _get_write_effects(opcode, ignore_msize)


@lru_cache
def _get_effects(opcode, ignore_msize):
    return _get_read_effects(opcode, ignore_msize) | _get_write_effects(opcode, ignore_msize)


@dataclass
class _Expression:
    opcode: str
    # the child is either expression of operand since
    # there are possibilities for cycles
    operands: list[IROperand | _Expression]
    cache_hash: int | None = None

    # equality for lattices only based on original instruction
    def __eq__(self, other) -> bool:
        if not isinstance(other, _Expression):
            return False
        return self.same(other)

    def __hash__(self) -> int:
        # Unfortunately the hash has been the performance
        # bottle neck in some cases so I cached the value
        if self.cache_hash is None:
            # the reason for the sort is that some opcodes could
            # be commutative and in that case the order of the
            # operands would not matter (so this is needed)
            # for correct implementation of hash (x == x => hash(x) == hash(y))
            self.cache_hash = hash((self.opcode, tuple(sorted(hash(op) for op in self.operands))))
        return self.cache_hash

    # Full equality for expressions based on opcode and operands
    def same(self, other) -> bool:
        if self is other:
            return True

        if self.opcode != other.opcode:
            return False

        # Early return special case for commutative instructions
        if self.is_commutative:
            if same_ops(self.operands, list(reversed(other.operands))):
                return True

        return same_ops(self.operands, other.operands)

    def __repr__(self) -> str:
        if self.opcode == "assign":
            assert len(self.operands) == 1, "wrong store"
            return repr(self.operands[0])
        res = self.opcode + "("
        res += ",".join(repr(op) for op in self.operands)
        res += ")"
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

    @property
    def is_commutative(self) -> bool:
        return self.opcode in COMMUTATIVE_INSTRUCTIONS


def same_ops(a_ops: list[IROperand | _Expression], b_ops: list[IROperand | _Expression]) -> bool:
    assert len(a_ops) == len(b_ops)
    for self_op, other_op in zip(a_ops, b_ops):
        if type(self_op) is not type(other_op):
            return False
        if isinstance(self_op, IROperand) and self_op != other_op:
            return False
        if isinstance(self_op, _Expression) and self_op is not other_op:
            return False

    return True


class _AvailableExpressions:
    """
    Class that holds available expression
    and provides API for handling them
    """

    exprs: immutables.Map[_Expression, list[IRInstruction]]

    def __init__(self):
        self.exprs = immutables.Map()

    def __eq__(self, other) -> bool:
        if not isinstance(other, _AvailableExpressions):
            return False

        return self.exprs == other.exprs

    def __repr__(self) -> str:
        res = "available expr\n"
        for key, val in self.exprs.items():
            res += f"\t{key}: {val}\n"
        return res

    def add(self, expr: _Expression, src_inst: IRInstruction):
        with self.exprs.mutate() as mt:
            if expr not in mt:
                mt[expr] = []
            else:
                mt[expr] = mt[expr].copy()
            mt[expr].append(src_inst)
            self.exprs = mt.finish()

    def remove_effect(self, effect: Effects, ignore_msize):
        if effect == effects.EMPTY:
            return
        to_remove = set()
        for expr in self.exprs.keys():
            op_effect = _get_effects(expr.opcode, ignore_msize)
            if op_effect & effect != effects.EMPTY:
                to_remove.add(expr)

        with self.exprs.mutate() as mt:
            for expr in to_remove:
                del mt[expr]
            self.exprs = mt.finish()

    def get_source_instruction(self, expr: _Expression) -> IRInstruction | None:
        """
        Get source instruction of expression if currently available
        """
        tmp = self.exprs.get(expr)
        if tmp is not None:
            # arbitrarily choose the first instruction
            return tmp[0]
        return None

    def copy(self) -> _AvailableExpressions:
        res = _AvailableExpressions()
        res.exprs = self.exprs
        return res

    @staticmethod
    def lattice_meet(lattices: list[_AvailableExpressions]):
        if len(lattices) == 0:
            return _AvailableExpressions()
        res = lattices[0].copy()
        # compute intersection
        for item in lattices[1:]:
            tmp = res
            res = _AvailableExpressions()
            mt = res.exprs.mutate()
            for expr, insts in item.exprs.items():
                if expr not in tmp.exprs:
                    continue
                new_insts = []
                for i in tmp.exprs[expr]:
                    if i in insts:
                        new_insts.append(i)
                if len(new_insts) == 0:
                    continue
                mt[expr] = new_insts
            res.exprs = mt.finish()
        return res


class AvailableExpressionAnalysis(IRAnalysis):
    """
    This analysis implements the standard available expression analysis,
    keeping track of effects and invalidated expressions.
    (https://en.wikipedia.org/wiki/Available_expression)
    """

    inst_to_expr: dict[IRInstruction, _Expression]
    dfg: DFGAnalysis
    cfg: CFGAnalysis
    inst_to_available: dict[IRInstruction, _AvailableExpressions]
    bb_ins: dict[IRBasicBlock, _AvailableExpressions]
    bb_outs: dict[IRBasicBlock, _AvailableExpressions]

    ignore_msize: bool

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self.inst_to_expr = dict()
        self.inst_to_available = dict()
        self.bb_ins = dict()
        self.bb_outs = dict()

        self.ignore_msize = not self._contains_msize()

    def analyze(self):
        worklist = deque()
        worklist.append(self.function.entry)
        while len(worklist) > 0:
            bb: IRBasicBlock = worklist.popleft()
            if self._handle_bb(bb):
                worklist.extend(self.cfg.cfg_out(bb))

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
        preds = self.cfg.cfg_in(bb)
        available_exprs = _AvailableExpressions.lattice_meet(
            [self.bb_outs.get(pred, _AvailableExpressions()) for pred in preds]
        )

        if bb in self.bb_ins and self.bb_ins[bb] == available_exprs:
            return False

        self.bb_ins[bb] = available_exprs.copy()

        change = False
        for inst in bb.instructions:
            if inst.opcode == "assign" or inst.is_pseudo or inst.is_bb_terminator:
                continue

            if (
                inst not in self.inst_to_available
                or available_exprs != self.inst_to_available[inst]
            ):
                self.inst_to_available[inst] = available_exprs.copy()

            expr = self._mk_expr(inst, available_exprs)
            # get an existing instance if it is available,
            # this makes `same()` faster.
            expr = self._get_available_expression(expr, available_exprs)

            self._update_expr(inst, expr)

            write_effects = _get_write_effects(expr.opcode, self.ignore_msize)
            available_exprs.remove_effect(write_effects, self.ignore_msize)

            # nonidempotent instructions affect other instructions,
            # but since it cannot be substituted it should not be
            # added to available exprs
            if inst.opcode in NONIDEMPOTENT_INSTRUCTIONS:
                continue

            expr_effects = _get_overlap_effects(expr.opcode, self.ignore_msize)
            if expr_effects == effects.EMPTY:
                available_exprs.add(expr, inst)

        if bb not in self.bb_outs or available_exprs != self.bb_outs[bb]:
            self.bb_outs[bb] = available_exprs
            # change is only necessery when the output of the
            # basic block is changed (otherwise it wont affect rest)
            change |= True

        return change

    def _get_operand(
        self, op: IROperand, available_exprs: _AvailableExpressions
    ) -> IROperand | _Expression:
        if not isinstance(op, IRVariable):
            return op
        inst = self.dfg.get_producing_instruction(op)
        assert inst is not None, op
        # the phi condition is here because it is only way to
        # create dataflow loop
        if inst.opcode == "phi":
            return op
        if inst.opcode == "assign":
            return self._get_operand(inst.operands[0], available_exprs)
        if inst.opcode == "param":
            return op
        # source is a magic opcode for tests
        if inst.opcode == "source":
            return op

        assert inst in self.inst_to_expr, f"operand source was not handled, ({op}, {inst})"
        return self.inst_to_expr[inst]

    def get_expression(self, inst: IRInstruction) -> tuple[_Expression, IRInstruction] | None:
        available_exprs = self.inst_to_available.get(inst, _AvailableExpressions())

        expr = self.inst_to_expr.get(inst)
        if expr is None:
            return None
        src = available_exprs.get_source_instruction(expr)
        if src is None:
            return None
        assert src != inst  # unreachable state
        return (expr, src)

    def get_from_same_bb(self, inst: IRInstruction, expr: _Expression) -> list[IRInstruction]:
        available_exprs = self.inst_to_available.get(inst, _AvailableExpressions())
        res = available_exprs.exprs[expr]
        return [i for i in res if i != inst and i.parent == inst.parent]

    def _mk_expr(self, inst: IRInstruction, available_exprs: _AvailableExpressions) -> _Expression:
        operands: list[IROperand | _Expression] = [
            self._get_operand(op, available_exprs) for op in inst.operands
        ]
        expr = _Expression(inst.opcode, operands)

        return expr

    def _get_available_expression(
        self, expr: _Expression, available_exprs: _AvailableExpressions
    ) -> _Expression:
        """
        Check if the expression is already in available expressions
        is so then return that instance
        """
        src_inst = available_exprs.get_source_instruction(expr)
        if src_inst is not None:
            same_expr = self.inst_to_expr[src_inst]
            return same_expr

        return expr

    def _update_expr(self, inst: IRInstruction, expr: _Expression):
        self.inst_to_expr[inst] = expr
