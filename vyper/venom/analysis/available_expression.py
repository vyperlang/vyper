from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from functools import cached_property

import vyper.venom.effects as effects
from vyper.venom.analysis.analysis import IRAnalysesCache, IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.basicblock import (
    BB_TERMINATORS,
    COMMUTATIVE_INSTRUCTIONS,
    IRBasicBlock,
    IRInstruction,
    IROperand,
    IRVariable,
)
from vyper.venom.context import IRFunction
from vyper.venom.effects import Effects

NONIDEMPOTENT_INSTRUCTIONS = frozenset(["log", "call", "staticcall", "delegatecall", "invoke"])

# instructions that queries info about current
# environment this is done because we know that
# all these instruction should have always
# the same value in function


# instruction that dont need to be stored in available expression
UNINTERESTING_OPCODES = frozenset(
    [
        "calldatasize",
        "gaslimit",
        "address",
        "codesize",
        "store",
        "phi",
        "param",
        "nop",
        "returndatasize",
        "gas",
        "gasprice",
        "origin",
        "coinbase",
        "timestamp",
        "number",
        "prevrandao",
        "chainid",
        "basefee",
        "blobbasefee",
        "pc",
        "msize",
    ]
)


#@dataclass(frozen=True)
@dataclass
class _Expression:
    # inst: IRInstruction
    opcode: str
    # the child is either expression of operand since
    # there are possibilities for cycles
    operands: list[IROperand | _Expression]
    ignore_msize: bool
    cache_hash: int = None

    # equality for lattices only based on original instruction
    def __eq__(self, other) -> bool:
        if not isinstance(other, _Expression):
            return False
        return self.same(other)

    def __hash__(self) -> int:
        if self.cache_hash is None:
            self.cache_hash = hash((self.opcode, tuple(sorted(self.operands, key=lambda x: str(x)))))
        return self.cache_hash

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
        # res += f" {self.inst.output} {self.inst.parent.label}"
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
        tmp_reads = effects.reads.get(self.opcode, effects.EMPTY)
        # tmp_reads = self.inst.get_read_effects()
        if self.ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads

    def get_writes(self) -> Effects:
        tmp_reads = effects.writes.get(self.opcode, effects.EMPTY)
        # tmp_reads = self.inst.get_write_effects()
        if self.ignore_msize:
            tmp_reads &= ~Effects.MSIZE
        return tmp_reads

    @property
    def is_commutative(self) -> bool:
        return self.opcode in COMMUTATIVE_INSTRUCTIONS
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
        if type(self_op) != type(other_op):
            return False
        if isinstance(self_op, IROperand) and self_op != other_op:
            return False
        if isinstance(self_op, _Expression) and self_op is not other_op:
            return False

    return True


class _AvailableExpression:
    """
    Class that holds available expression
    and provides API for handling them
    """

    buckets: dict[_Expression, list[IRInstruction]]

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

    def add(self, expr: _Expression, src_inst: IRInstruction):
        if expr not in self.buckets:
            self.buckets[expr] = []
        self.buckets[expr].append(src_inst)

    def remove_effect(self, effect: Effects):
        #breakpoint()
        if effect == effects.EMPTY:
            return
        to_remove = set()
        for expr in self.buckets.keys():
            read_effs = expr.get_reads()
            write_effs = expr.get_writes()
            op_effect = read_effs | write_effs
            if op_effect & effect != effects.EMPTY:
                to_remove.add(expr)

        for expr in to_remove:
            del self.buckets[expr]

    def get_source(self, expr: _Expression) -> IRInstruction | None:
        """
        Get source instruction of expression if currently available
        """
        tmp = self.buckets.get(expr)
        if tmp is not None:
            return tmp[0]
        return None

    def copy(self) -> _AvailableExpression:
        res = _AvailableExpression()
        res.buckets = self.buckets.copy()
        return res

    @staticmethod
    def intersection(*others: _AvailableExpression | None):
        tmp = list(o for o in others if o is not None)
        if len(tmp) == 0:
            return _AvailableExpression()
        res = tmp[0].copy()
        for item in tmp[1:]:
            tmp_res = res
            res = _AvailableExpression()
            for expr, inst in item.buckets.items():
                if expr not in tmp_res.buckets:
                    continue
                if tmp_res.buckets[expr] != inst:
                    continue
                res.buckets[expr] = inst
        return res


class CSEAnalysis(IRAnalysis):
    inst_to_expr: dict[IRInstruction, _Expression]
    dfg: DFGAnalysis
    inst_to_available: dict[IRInstruction, _AvailableExpression]
    bb_ins: dict[IRBasicBlock, _AvailableExpression]
    bb_outs: dict[IRBasicBlock, _AvailableExpression]

    ignore_msize: bool

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        assert isinstance(dfg, DFGAnalysis)
        self.dfg = dfg

        self.inst_to_expr = dict()
        self.inst_to_available = dict()
        self.bb_ins = dict()
        self.bb_outs = dict()

        self.ignore_msize = not self._contains_msize()

    def analyze(self):
        #print("start", self.function.name)
        worklist = deque()
        worklist.append(self.function.entry)
        while len(worklist) > 0:
            bb: IRBasicBlock = worklist.popleft()
            if self._handle_bb(bb):
                worklist.extend(bb.cfg_out)
        #print("end", self.function.name)

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
        #print(bb.label)
        #breakpoint()
        available_expr: _AvailableExpression = _AvailableExpression.intersection(
            *(self.bb_outs.get(out_bb, _AvailableExpression()) for out_bb in bb.cfg_in)
        )

        if bb in self.bb_ins and self.bb_ins[bb] == available_expr:
            return False

        self.bb_ins[bb] = available_expr.copy()

        change = False
        for inst in bb.instructions:
            if inst.opcode in UNINTERESTING_OPCODES or inst.opcode in BB_TERMINATORS:
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

            if expr.get_writes() & expr.get_reads() == effects.EMPTY:
                available_expr.add(expr, inst)

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
            assert inst is not None, op
            # the phi condition is here because it is only way to
            # create dataflow loop
            if inst.opcode == "phi":
                return op
            if inst.opcode == "store":
                return self._get_operand(inst.operands[0], available_exprs)
            if inst in self.inst_to_expr:
                e = self.inst_to_expr[inst]
                same_insts = available_exprs.buckets.get(e, [])
                if inst in same_insts:
                    return self.inst_to_expr[same_insts[0]]
                return e
            assert inst.opcode in UNINTERESTING_OPCODES
            return self._get_expression(inst, available_exprs)
        return op

    def get_expression(
        self, inst: IRInstruction, available_exprs: _AvailableExpression | None = None
    ) -> tuple[_Expression, IRInstruction]:
        if available_exprs is None:
            available_exprs = self.inst_to_available.get(inst, _AvailableExpression())

        assert available_exprs is not None  # help mypy
        expr = self.inst_to_expr.get(inst)
        if expr is None:
            expr = self._get_expression(inst, available_exprs)
        src = available_exprs.get_source(expr)
        if src is None:
            src = inst
        return (expr, src)

    def _get_expression(
        self, inst: IRInstruction, available_exprs: _AvailableExpression
    ) -> _Expression:

        # create expression
        operands: list[IROperand | _Expression] = [
            self._get_operand(op, available_exprs) for op in inst.operands
        ]
        expr = _Expression(inst.opcode, operands, self.ignore_msize)

        src_inst = available_exprs.get_source(expr)
        if src_inst is not None:
            same_expr = self.inst_to_expr[src_inst]
            if same_expr is not None:
                self.inst_to_expr[inst] = same_expr
                return same_expr

        self.inst_to_expr[inst] = expr
        return expr
