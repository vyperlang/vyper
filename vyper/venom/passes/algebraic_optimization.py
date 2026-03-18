from dataclasses import dataclass
from enum import Enum, auto

from vyper.utils import SizeLimits, int_bounds, int_log2, is_power_of_two, wrap256
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.analysis.variable_range import VariableRangeAnalysis
from vyper.venom.basicblock import (
    COMPARATOR_INSTRUCTIONS,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
    flip_comparison_opcode,
)
from vyper.venom.passes.base_pass import InstUpdater, IRPass

TRUTHY_INSTRUCTIONS = ("iszero", "jnz", "assert", "assert_unreachable")


def lit_eq(op: IROperand, val: int) -> bool:
    return isinstance(op, IRLiteral) and wrap256(op.value) == wrap256(val)


def _push_size(value: int) -> int:
    """Number of data bytes needed for a PUSH instruction."""
    value = wrap256(value)
    if value == 0:
        return 0  # PUSH0
    return (value.bit_length() + 7) // 8


# --- VarInfo ADT (pure, immutable) ---


class VarInfoKind(Enum):
    UNKNOWN = auto()  # no information
    AFFINE = auto()  # base + offset


@dataclass(frozen=True, slots=True)
class VarInfo:
    _kind: VarInfoKind
    _base: IROperand | None  # for AFFINE: the root variable (None = pure constant)
    _offset: int  # for AFFINE: the constant offset (wrap256)

    @classmethod
    def unknown(cls) -> "VarInfo":
        return cls(_kind=VarInfoKind.UNKNOWN, _base=None, _offset=0)

    @classmethod
    def affine(cls, base: IROperand | None, offset: int) -> "VarInfo":
        return cls(_kind=VarInfoKind.AFFINE, _base=base, _offset=wrap256(offset))

    @property
    def is_affine(self) -> bool:
        return self._kind == VarInfoKind.AFFINE

    @property
    def is_unknown(self) -> bool:
        return self._kind == VarInfoKind.UNKNOWN


# --- Pure transfer functions (module-level, no self) ---


def _lookup(op: IROperand, info: dict[IRVariable, VarInfo]) -> VarInfo:
    """Look up the VarInfo for an operand."""
    if isinstance(op, IRVariable):
        if op in info:
            return info[op]
        return VarInfo.affine(op, 0)
    if isinstance(op, IRLiteral):
        return VarInfo.affine(None, op.value)
    # IRLabel or other
    return VarInfo.unknown()


def transfer_add(lhs: VarInfo, rhs: VarInfo, out: IRVariable) -> VarInfo:
    """Pure: (VarInfo, VarInfo, output_var) -> VarInfo for add."""
    if lhs.is_affine and rhs.is_affine:
        if lhs._base is None:
            return VarInfo.affine(rhs._base, rhs._offset + lhs._offset)
        if rhs._base is None:
            return VarInfo.affine(lhs._base, lhs._offset + rhs._offset)
    return VarInfo.affine(out, 0)


def transfer_sub(minuend: VarInfo, subtrahend: VarInfo, out: IRVariable) -> VarInfo:
    """Pure: (VarInfo, VarInfo, output_var) -> VarInfo for sub
    (minuend - subtrahend)."""
    if minuend.is_affine and subtrahend.is_affine:
        if subtrahend._base is None:
            return VarInfo.affine(
                minuend._base, minuend._offset - subtrahend._offset
            )
    return VarInfo.affine(out, 0)


def transfer_assign(src: VarInfo) -> VarInfo:
    """Pure: VarInfo -> VarInfo (inherit)."""
    return VarInfo(src._kind, src._base, src._offset)


class AlgebraicOptimizationPass(IRPass):
    """
    This pass reduces algebraic evaluatable expressions.

    It currently optimizes:
      - iszero chains
      - binops
      - offset adds
      - affine chain folding (lattice-driven)
      - signextend elimination via range analysis
    """

    dfg: DFGAnalysis
    updater: InstUpdater
    range_analysis: VariableRangeAnalysis
    var_info: dict[IRVariable, VarInfo]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.range_analysis = self.analyses_cache.force_analysis(VariableRangeAnalysis)
        self.updater = InstUpdater(self.dfg)
        self._handle_offset()

        self.var_info = self._compute_var_info()
        self._rewrite_all()
        self._optimize_iszero_chains()
        self.var_info = self._compute_var_info()
        self._rewrite_all()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    # --- Forward propagation (imperative shell) ---

    def _compute_var_info(self) -> dict[IRVariable, VarInfo]:
        info: dict[IRVariable, VarInfo] = {}
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.num_outputs != 1:
                    continue
                if inst.opcode == "add":
                    lhs = _lookup(inst.operands[1], info)
                    rhs = _lookup(inst.operands[0], info)
                    info[inst.output] = transfer_add(lhs, rhs, inst.output)
                elif inst.opcode == "sub":
                    # sub computes operands[1] - operands[0]
                    minuend = _lookup(inst.operands[1], info)
                    subtrahend = _lookup(inst.operands[0], info)
                    info[inst.output] = transfer_sub(minuend, subtrahend, inst.output)
                elif inst.opcode == "assign":
                    info[inst.output] = transfer_assign(_lookup(inst.operands[0], info))
                else:
                    info[inst.output] = VarInfo.affine(inst.output, 0)
        return info

    # --- Rewrite phase (imperative shell) ---

    def _rewrite_all(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                self._rewrite_inst(inst)
                self._flip_inst(inst)

    def _rewrite_inst(self, inst: IRInstruction):
        if inst.num_outputs != 1:
            return
        if inst.is_volatile or inst.opcode == "assign" or inst.is_pseudo:
            return
        if self._rewrite_affine(inst):
            return
        if self._rewrite_producer(inst):
            return
        self._rewrite_local(inst)

    def _rewrite_affine(self, inst: IRInstruction) -> bool:
        """Lattice-driven affine chain folding."""
        if inst.opcode not in ("add", "sub"):
            return False
        vi = self.var_info.get(inst.output)
        if vi is None or not vi.is_affine or vi._base is None:
            return False

        base = vi._base
        offset = vi._offset
        if base == inst.output:
            return False

        # Find the immediate variable operand and current literal
        if inst.opcode == "add":
            val_op, lit_op = self._extract_value_and_literal_operands(inst)
            if val_op is None or lit_op is None:
                return False
            imm_base = val_op
            curr_lit = lit_op.value
        else:  # sub
            op0, op1 = inst.operands
            if not isinstance(op0, IRLiteral) or isinstance(op1, IRLiteral):
                return False
            imm_base = op1
            curr_lit = op0.value

        # Only rewrite if chain folding found a deeper base
        if base == imm_base:
            return False

        # Only fold through single-use intermediates — folding through
        # multi-use doesn't eliminate instructions and the variable
        # reference change can increase DUP depth in codegen
        if isinstance(imm_base, IRVariable) and not self.dfg.is_single_use(imm_base):
            return False

        if offset == 0:
            self.updater.mk_assign(inst, base)
            return True

        # Don't rewrite if it would increase literal byte width
        if _push_size(offset) > _push_size(curr_lit):
            return False

        self.updater.update(inst, "add", [base, IRLiteral(offset)])
        return True

    def _rewrite_producer(self, inst: IRInstruction) -> bool:
        """Producer-based pattern rewrites."""
        operands = inst.operands

        # balance(address()) -> selfbalance()
        # note: extcodesize(address()) -> codesize() is NOT safe because
        # during initcode EXTCODESIZE(ADDRESS()) returns 0 while CODESIZE
        # returns the initcode length.
        if inst.opcode == "balance":
            op = operands[0]
            if isinstance(op, IRVariable):
                producer = self.dfg.get_producing_instruction(op)
                if producer is not None and producer.opcode == "address":
                    self.updater.update(inst, "selfbalance", [])
            return True  # no other rules for balance

        if inst.opcode == "extcodesize":
            return True  # no optimizations for extcodesize

        # signextend(n, signextend(m, x)) where n >= m -> signextend(m, x)
        if inst.opcode == "signextend":
            n_op = operands[-1]
            x_op = operands[-2]
            if isinstance(x_op, IRVariable) and self._is_lit(n_op):
                producer = self.dfg.get_producing_instruction(x_op)
                if producer is not None and producer.opcode == "signextend":
                    inner_n = producer.operands[-1]
                    if self._is_lit(inner_n) and n_op.value >= inner_n.value:
                        self.updater.mk_assign(inst, x_op)
                        return True

        return False

    # --- Local peephole rules ---

    def _rewrite_local(self, inst: IRInstruction):
        operands = inst.operands
        inst_out = inst.output

        # TODO nice to have rules:
        # -1 * x => 0 - x
        # x // -1 => 0 - x (?)
        # x + (-1) => x - 1  # save codesize, maybe for all negative numbers)
        # 1 // x => x == 1(?)
        # 1 % x => x > 1(?)
        # !!x => x > 0  # saves 1 gas as of shanghai

        # make logic easier for commutative instructions.
        if inst.flippable and self._is_lit(operands[1]) and not self._is_lit(operands[0]):
            inst.flip()
            operands = inst.operands

        if inst.opcode in {"shl", "shr", "sar"}:
            # (x >> 0) == (x << 0) == x
            if lit_eq(operands[1], 0):
                self.updater.mk_assign(inst, operands[0])
                return
            # no more cases for these instructions
            return

        if inst.opcode == "signextend":
            # text: signextend n, x -> operands[-1]=n (bytes), operands[-2]=x (value)
            n_op = operands[-1]  # byte count
            x_op = operands[-2]  # value

            # signextend(n, x) where n >= 31 is always a no-op
            if self._is_lit(n_op) and n_op.value >= 31:
                self.updater.mk_assign(inst, x_op)
                return

            # Range-based elimination: if x is already in the valid signed range
            # for (n+1) bytes, signextend is a no-op
            if self._is_lit(n_op):
                n = n_op.value
                if 0 <= n < 31:
                    x_range = self.range_analysis.get_range(x_op, inst)
                    if not x_range.is_top:
                        # Compute valid signed range for (n+1) bytes
                        bits = 8 * (n + 1)
                        signed_min = -(1 << (bits - 1))
                        signed_max = (1 << (bits - 1)) - 1
                        # If x is already in valid range, signextend is no-op
                        if x_range.lo >= signed_min and x_range.hi <= signed_max:
                            self.updater.mk_assign(inst, x_op)
                            return
            return

        if inst.opcode == "exp":
            # x ** 0 -> 1
            if lit_eq(operands[0], 0):
                self.updater.mk_assign(inst, IRLiteral(1))
                return

            # 1 ** x -> 1
            if lit_eq(operands[1], 1):
                self.updater.mk_assign(inst, IRLiteral(1))
                return

            # 0 ** x -> iszero x
            if lit_eq(operands[1], 0):
                self.updater.update(inst, "iszero", [operands[0]])
                return

            # x ** 1 -> x
            if lit_eq(operands[0], 1):
                self.updater.mk_assign(inst, operands[1])
                return

            # no more cases for this instruction
            return

        if inst.opcode == "gep":
            if lit_eq(inst.operands[1], 0):
                self.updater.mk_assign(inst, inst.operands[0])
            return

        if inst.opcode in {"add", "sub", "xor"}:
            # (x - x) == (x ^ x) == 0
            if inst.opcode in ("xor", "sub") and operands[0] == operands[1]:
                self.updater.mk_assign(inst, IRLiteral(0))
                return

            # (x + 0) == (0 + x)  -> x
            # x - 0 -> x
            # (x ^ 0) == (0 ^ x)  -> x
            if lit_eq(operands[0], 0):
                self.updater.mk_assign(inst, operands[1])
                return

            # (-1) - x -> ~x
            # from two's complement
            if inst.opcode == "sub" and lit_eq(operands[1], -1):
                self.updater.update(inst, "not", [operands[0]])
                return

            # x ^ 0xFFFF..FF -> ~x
            if inst.opcode == "xor" and lit_eq(operands[0], -1):
                self.updater.update(inst, "not", [operands[1]])
                return

            return

        # x & 0xFF..FF -> x
        if inst.opcode == "and" and lit_eq(operands[0], -1):
            self.updater.mk_assign(inst, operands[1])
            return

        if inst.opcode in ("mul", "and", "div", "sdiv", "mod", "smod"):
            # (x * 0) == (x & 0) == (x // 0) == (x % 0) -> 0
            if any(lit_eq(op, 0) for op in operands):
                self.updater.mk_assign(inst, IRLiteral(0))
                return

        if inst.opcode in {"mul", "div", "sdiv", "mod", "smod"}:
            if inst.opcode in ("mod", "smod") and lit_eq(operands[0], 1):
                # x % 1 -> 0
                self.updater.mk_assign(inst, IRLiteral(0))
                return

            # (x * 1) == (1 * x) == (x // 1)  -> x
            if inst.opcode in ("mul", "div", "sdiv") and lit_eq(operands[0], 1):
                self.updater.mk_assign(inst, operands[1])
                return

            if self._is_lit(operands[0]) and is_power_of_two(operands[0].value):
                val = operands[0].value
                # x % (2^n) -> x & (2^n - 1)
                if inst.opcode == "mod":
                    self.updater.update(inst, "and", [IRLiteral(val - 1), operands[1]])
                    return
                # x / (2^n) -> x >> n
                if inst.opcode == "div":
                    self.updater.update(inst, "shr", [operands[1], IRLiteral(int_log2(val))])
                    return
                # x * (2^n) -> x << n
                if inst.opcode == "mul":
                    self.updater.update(inst, "shl", [operands[1], IRLiteral(int_log2(val))])
                    return
            return

        uses = self.dfg.get_uses(inst_out)

        is_truthy = all(i.opcode in TRUTHY_INSTRUCTIONS for i in uses)
        prefer_iszero = all(i.opcode in ("assert", "iszero") for i in uses)

        # TODO rules like:
        # not x | not y => not (x & y)
        # x | not y => not (not x & y)

        if inst.opcode == "or":
            # x | 0xff..ff == 0xff..ff
            if any(lit_eq(op, SizeLimits.MAX_UINT256) for op in operands):
                self.updater.mk_assign(inst, IRLiteral(SizeLimits.MAX_UINT256))
                return

            # x | n -> 1 in truthy positions (if n is non zero)
            if is_truthy and self._is_lit(operands[0]) and operands[0].value != 0:
                self.updater.mk_assign(inst, IRLiteral(1))
                return

            # x | 0 -> x
            if lit_eq(operands[0], 0):
                self.updater.mk_assign(inst, operands[1])
                return

        if inst.opcode == "eq":
            # x == x -> 1
            if operands[0] == operands[1]:
                self.updater.mk_assign(inst, IRLiteral(1))
                return

            # x == 0 -> iszero x
            if lit_eq(operands[0], 0):
                self.updater.update(inst, "iszero", [operands[1]])
                return

            # eq x -1 -> iszero(~x)
            # (saves codesize, not gas)
            if lit_eq(operands[0], -1):
                var = self.updater.add_before(inst, "not", [operands[1]])
                assert var is not None  # help mypy
                self.updater.update(inst, "iszero", [var])
                return

            if prefer_iszero:
                # (eq x y) has the same truthyness as (iszero (xor x y))
                tmp = self.updater.add_before(inst, "xor", [operands[0], operands[1]])

                assert tmp is not None  # help mypy
                self.updater.update(inst, "iszero", [tmp])
                return

        if inst.opcode in COMPARATOR_INSTRUCTIONS:
            self._optimize_comparator_instruction(inst, prefer_iszero)

    # --- Unchanged methods ---

    def _optimize_iszero_chains(self) -> None:
        fn = self.function
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "iszero":
                    continue

                iszero_chain = self._get_iszero_chain(inst.operands[0])
                iszero_count = len(iszero_chain)
                if iszero_count == 0:
                    continue

                inst_out = inst.output
                for use_inst in self.dfg.get_uses(inst_out).copy():
                    opcode = use_inst.opcode

                    if opcode == "iszero":
                        # We keep iszero instuctions as is
                        continue
                    if opcode in ("jnz", "assert", "assert_unreachable"):
                        # instructions that accept a truthy value as input:
                        # we can remove up to all the iszero instructions
                        keep_count = 1 - iszero_count % 2
                    else:
                        # all other instructions:
                        # we need to keep at least one or two iszero instructions
                        keep_count = 1 + iszero_count % 2

                    if keep_count >= iszero_count:
                        continue

                    out_var = iszero_chain[keep_count].operands[0]
                    self.updater.update_operands(use_inst, {inst_out: out_var})

    def _get_iszero_chain(self, op: IROperand) -> list[IRInstruction]:
        chain: list[IRInstruction] = []

        while True:
            if not isinstance(op, IRVariable):
                break
            inst = self.dfg.get_producing_instruction(op)
            if inst is None or inst.opcode != "iszero":
                break
            op = inst.operands[0]
            chain.append(inst)

        chain.reverse()
        return chain

    def _handle_offset(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if (
                    inst.opcode == "add"
                    and self._is_lit(inst.operands[0])
                    and isinstance(inst.operands[1], IRLabel)
                ):
                    inst.opcode = "offset"

    def _is_lit(self, operand: IROperand) -> bool:
        return isinstance(operand, IRLiteral)

    def _extract_value_and_literal_operands(
        self, inst: IRInstruction
    ) -> tuple[IROperand | None, IRLiteral | None]:
        value_op = None
        literal_op = None
        for op in inst.operands:
            if self._is_lit(op):
                if literal_op is not None:
                    return None, None
                literal_op = op
            else:
                value_op = op
        assert isinstance(literal_op, IRLiteral) or literal_op is None  # help mypy
        return value_op, literal_op

    def _flip_inst(self, inst: IRInstruction):
        ops = inst.operands
        # improve code. this seems like it should be properly handled by
        # better heuristics in DFT pass.
        if inst.flippable and self._is_lit(ops[0]) and not self._is_lit(ops[1]):
            inst.flip()

    def _optimize_comparator_instruction(self, inst, prefer_iszero):
        opcode, operands = inst.opcode, inst.operands
        assert opcode in COMPARATOR_INSTRUCTIONS  # sanity
        inst_out = inst.output

        # (x > x) == (x < x) -> 0
        if operands[0] == operands[1]:
            self.updater.mk_assign(inst, IRLiteral(0))
            return

        is_gt = "g" in opcode
        signed = "s" in opcode

        # Range-based comparison optimization
        # Semantics: lt a, b computes a < b; gt a, b computes a > b
        # operands[-1] = a (first in text), operands[-2] = b (second in text)
        # We can optimize when one operand is a literal and we have range info for the other
        a_op = operands[-1]  # first in text
        b_op = operands[-2]  # second in text

        if self._is_lit(a_op) and not self._is_lit(b_op):
            # a is literal, b is variable: comparing lit <?> var
            lit = a_op.value
            var_range = self.range_analysis.get_range(b_op, inst)
            if not var_range.is_top and not var_range.is_empty:
                if signed:
                    if var_range.hi <= SizeLimits.MAX_INT256:
                        lit = wrap256(lit, signed=True)
                    else:
                        lit = None
                else:
                    if var_range.lo >= 0:
                        lit = wrap256(lit)
                    else:
                        lit = None

                if lit is not None:
                    if is_gt:
                        # lit > var: always true if lit > var.hi, always false if lit <= var.lo
                        if lit > var_range.hi:
                            self.updater.mk_assign(inst, IRLiteral(1))
                            return
                        if lit <= var_range.lo:
                            self.updater.mk_assign(inst, IRLiteral(0))
                            return
                    else:
                        # lit < var: always true if lit < var.lo, always false if lit >= var.hi
                        if lit < var_range.lo:
                            self.updater.mk_assign(inst, IRLiteral(1))
                            return
                        if lit >= var_range.hi:
                            self.updater.mk_assign(inst, IRLiteral(0))
                            return

        elif self._is_lit(b_op) and not self._is_lit(a_op):
            # a is variable, b is literal: comparing var <?> lit
            lit = b_op.value
            var_range = self.range_analysis.get_range(a_op, inst)
            if not var_range.is_top and not var_range.is_empty:
                if signed:
                    if var_range.hi <= SizeLimits.MAX_INT256:
                        lit = wrap256(lit, signed=True)
                    else:
                        lit = None
                else:
                    if var_range.lo >= 0:
                        lit = wrap256(lit)
                    else:
                        lit = None

                if lit is not None:
                    if is_gt:
                        # var > lit: always true if var.lo > lit, always false if var.hi <= lit
                        if var_range.lo > lit:
                            self.updater.mk_assign(inst, IRLiteral(1))
                            return
                        if var_range.hi <= lit:
                            self.updater.mk_assign(inst, IRLiteral(0))
                            return
                    else:
                        # var < lit: always true if var.hi < lit, always false if var.lo >= lit
                        if var_range.hi < lit:
                            self.updater.mk_assign(inst, IRLiteral(1))
                            return
                        if var_range.lo >= lit:
                            self.updater.mk_assign(inst, IRLiteral(0))
                            return

        lo, hi = int_bounds(bits=256, signed=signed)

        if not isinstance(operands[0], IRLiteral):
            return

        # for comparison operators, we have three special boundary cases:
        # almost always, never and almost never.
        # almost_always is always true for the non-strict ("ge" and co)
        # comparators. for strict comparators ("gt" and co), almost_always
        # is true except for one case. never is never true for the strict
        # comparators. never is almost always false for the non-strict
        # comparators, except for one case. and almost_never is almost
        # never true (except one case) for the strict comparators.
        if is_gt:
            almost_always, never = lo, hi
            almost_never = hi - 1
        else:
            almost_always, never = hi, lo
            almost_never = lo + 1

        if lit_eq(operands[0], never):
            self.updater.mk_assign(inst, IRLiteral(0))
            return

        if lit_eq(operands[0], almost_never):
            # (lt x 1), (gt x (MAX_UINT256 - 1)), (slt x (MIN_INT256 + 1))

            self.updater.update(inst, "eq", [operands[1], IRLiteral(never)])
            return

        # rewrites. in positions where iszero is preferred, (gt x 5) => (ge x 6)
        if prefer_iszero and lit_eq(operands[0], almost_always):
            # e.g. gt x 0, slt x MAX_INT256
            tmp = self.updater.add_before(inst, "eq", operands)
            self.updater.update(inst, "iszero", [tmp])
            return

        # since push0 was introduced in shanghai, it's potentially
        # better to actually reverse this optimization -- i.e.
        # replace iszero(iszero(x)) with (gt x 0)
        if opcode == "gt" and lit_eq(operands[0], 0):
            tmp = self.updater.add_before(inst, "iszero", [operands[1]])
            self.updater.update(inst, "iszero", [tmp])
            return

        # rewrite comparisons by either inserting or removing an `iszero`,
        # e.g. `x > N` -> `x >= (N + 1)`
        uses = self.dfg.get_uses(inst_out)
        if len(uses) != 1:
            return

        after = uses.first()
        if after.opcode not in ("iszero", "assert"):
            return

        if after.opcode == "iszero":
            # peer down the iszero chain to see if it actually makes sense
            # to remove the iszero.
            n_uses = self.dfg.get_uses(after.output)
            if len(n_uses) != 1:  # block the optimization
                return
            # "assert" inserts an iszero in assembly, so we will have
            # two iszeros in the asm. this is already optimal, so we don't
            # apply the iszero insertion
            if n_uses.first().opcode == "assert":
                return

        val = wrap256(operands[0].value, signed=signed)
        assert val != never, "unreachable"  # sanity

        if is_gt:
            val += 1
        else:
            # TODO: if resulting val is -1 (0xFF..FF), disable this
            # when optimization level == codesize
            val -= 1

        # sanity -- implied by precondition that `val != never`
        assert wrap256(val, signed=signed) == val

        new_opcode = flip_comparison_opcode(opcode)

        self.updater.update(inst, new_opcode, [IRLiteral(val), operands[1]])

        insert_iszero = after.opcode == "assert"
        if insert_iszero:
            # next instruction is an assert, so we insert an iszero so
            # that there will be two iszeros in the assembly.
            assert len(after.operands) == 1, after
            var = self.updater.add_before(after, "iszero", [inst_out])
            self.updater.update_operands(after, {after.operands[0]: var})
        else:
            # remove the iszero!
            assert len(after.operands) == 1, after
            self.updater.update(after, "assign", after.operands)
