from dataclasses import dataclass

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
# Represents affine knowledge: value = base + offset (mod 2^256).
# base=None means a pure constant (offset only).


@dataclass(frozen=True, slots=True)
class VarInfo:
    base: IROperand | None  # root variable, or None for pure constant
    offset: int  # constant offset (wrap256)

    @classmethod
    def of(cls, base: IROperand | None, offset: int = 0) -> "VarInfo":
        return cls(base=base, offset=wrap256(offset))


# --- Pure transfer functions (module-level, no self) ---


def _lookup(op: IROperand, info: dict[IRVariable, VarInfo]) -> VarInfo:
    """Look up the VarInfo for an operand."""
    if isinstance(op, IRVariable):
        if op in info:
            return info[op]
        return VarInfo.of(op)
    if isinstance(op, IRLiteral):
        return VarInfo.of(None, op.value)
    assert isinstance(op, IRLabel)
    # IRLabel — tracked as opaque base (not decomposable)
    return VarInfo.of(op)


def transfer_add(lhs: VarInfo, rhs: VarInfo, out: IRVariable) -> VarInfo:
    """Pure: (VarInfo, VarInfo, output_var) -> VarInfo for add."""
    if lhs.base is None:
        return VarInfo.of(rhs.base, rhs.offset + lhs.offset)
    if rhs.base is None:
        return VarInfo.of(lhs.base, lhs.offset + rhs.offset)
    return VarInfo.of(out)


def transfer_sub(minuend: VarInfo, subtrahend: VarInfo, out: IRVariable) -> VarInfo:
    """Pure: (VarInfo, VarInfo, output_var) -> VarInfo for sub
    (minuend - subtrahend)."""
    if subtrahend.base is None:
        return VarInfo.of(minuend.base, minuend.offset - subtrahend.offset)
    return VarInfo.of(out)


def transfer_assign(src: VarInfo) -> VarInfo:
    """Pure: VarInfo -> VarInfo (inherit). VarInfo is frozen, so identity."""
    return src


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
    # (root, 1st_iszero_out, 2nd, ...) per chain output, built forward
    iszero_targets: dict[IRVariable, tuple[IROperand, ...]]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.range_analysis = self.analyses_cache.force_analysis(VariableRangeAnalysis)
        self.updater = InstUpdater(self.dfg)
        self._handle_offset()

        self.var_info, self.iszero_targets = self._compute_var_info()
        self._rewrite_all()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    # --- Forward propagation (imperative shell) ---

    def _compute_var_info(
        self,
    ) -> tuple[dict[IRVariable, VarInfo], dict[IRVariable, tuple[IROperand, ...]]]:
        info: dict[IRVariable, VarInfo] = {}
        targets: dict[IRVariable, tuple[IROperand, ...]] = {}
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.num_outputs != 1:
                    continue
                if inst.opcode == "add":
                    lhs = _lookup(inst.operands[1], info)
                    rhs = _lookup(inst.operands[0], info)
                    info[inst.output] = transfer_add(lhs, rhs, inst.output)
                elif inst.opcode == "sub":
                    minuend = _lookup(inst.operands[1], info)
                    subtrahend = _lookup(inst.operands[0], info)
                    info[inst.output] = transfer_sub(minuend, subtrahend, inst.output)
                elif inst.opcode == "assign":
                    info[inst.output] = transfer_assign(_lookup(inst.operands[0], info))
                else:
                    if inst.opcode == "iszero":
                        # build iszero chain targets: (root, 1st, 2nd, ...)
                        inp = inst.operands[0]
                        prev = (
                            targets[inp]
                            if isinstance(inp, IRVariable) and inp in targets
                            else (inp,)
                        )
                        targets[inst.output] = prev + (inst.output,)
                    info[inst.output] = VarInfo.of(inst.output)
        return info, targets

    # --- Rewrite phase (imperative shell) ---

    def _rewrite_all(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                self._rewrite_iszero_uses(inst)
                self._rewrite_inst(inst)
                self._flip_inst(inst)

    def _chain_valid(self, chain: tuple[IROperand, ...]) -> bool:
        """Verify iszero chain is still intact (not mutated by mid-pass rewrites)."""
        for var in chain[1:]:  # chain[0] is the root, skip it
            if not isinstance(var, IRVariable):
                return False
            prod = self.dfg.get_producing_instruction(var)
            if prod is None or prod.opcode != "iszero":
                return False
        return True

    def _rewrite_iszero_uses(self, inst: IRInstruction):
        """Shorten iszero chains at use sites via forward-computed targets."""
        if inst.opcode == "iszero":
            return  # iszero-to-iszero links are left alone

        replacements: dict[IROperand, IROperand] = {}
        for op in inst.operands:
            if not isinstance(op, IRVariable):
                continue
            chain = self.iszero_targets.get(op)
            if chain is None:
                continue

            # chain = (root, 1st_iszero_out, 2nd, ..., op)
            # depth = len(chain) - 1 (root is not an iszero)
            depth = len(chain) - 1
            if inst.opcode in ("jnz", "assert", "assert_unreachable"):
                keep = depth % 2
            else:
                keep = 2 - depth % 2

            if keep < depth and self._chain_valid(chain):
                replacements[op] = chain[keep]

        if len(replacements) > 0:
            self.updater.update_operands(inst, replacements)

    def _rewrite_inst(self, inst: IRInstruction):
        if inst.num_outputs != 1:
            return
        if inst.is_volatile or inst.opcode == "assign" or inst.is_pseudo:
            return
        if self._rewrite_affine(inst):
            return
        if self._rewrite_or_skip_producer(inst):
            return
        self._rewrite_local(inst)

    def _rewrite_affine(self, inst: IRInstruction) -> bool:
        """Lattice-driven affine chain folding."""
        if inst.opcode not in ("add", "sub"):
            return False
        vi = self.var_info.get(inst.output)
        if vi is None or vi.base is None:
            return False

        base = vi.base
        offset = vi.offset
        if base == inst.output:
            return False
        if isinstance(base, IRLabel):
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

        # Don't fold through multi-use intermediates — this destroys
        # CSE opportunities for shared base pointers (e.g. alloca+64
        # used by multiple mcopy destinations).
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

    def _rewrite_or_skip_producer(self, inst: IRInstruction) -> bool:
        """Producer-based pattern rewrites. Returns True if a rewrite was
        applied OR if the opcode should be skipped by _rewrite_local."""
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
        # normalize: literal to operands[0] for commutative ops
        if inst.flippable and self._is_lit(inst.operands[1]) and not self._is_lit(inst.operands[0]):
            inst.flip()

        opcode = inst.opcode
        if opcode in ("shl", "shr", "sar"):
            self._rule_shift(inst)
        elif opcode == "signextend":
            self._rule_signextend(inst)
        elif opcode == "exp":
            self._rule_exp(inst)
        elif opcode == "gep":
            self._rule_gep(inst)
        elif opcode in ("add", "sub", "xor"):
            self._rule_additive(inst)
        elif opcode == "and":
            self._rule_and(inst)
        elif opcode in ("mul", "div", "sdiv", "mod", "smod"):
            self._rule_multiplicative(inst)
        elif opcode == "or":
            self._rule_or(inst)
        elif opcode == "eq":
            self._rule_eq(inst)
        elif opcode in COMPARATOR_INSTRUCTIONS:
            uses = self.dfg.get_uses(inst.output)
            prefer_iszero = all(i.opcode in ("assert", "iszero") for i in uses)
            self._optimize_comparator_instruction(inst, prefer_iszero)

    # --- Per-opcode rewrite rules ---

    def _rule_shift(self, inst: IRInstruction):
        # (x >> 0) == (x << 0) == x
        if lit_eq(inst.operands[1], 0):
            self.updater.mk_assign(inst, inst.operands[0])

    def _rule_signextend(self, inst: IRInstruction):
        n_op = inst.operands[-1]  # byte count
        x_op = inst.operands[-2]  # value

        # signextend(n, x) where n >= 31 is always a no-op
        if self._is_lit(n_op) and n_op.value >= 31:
            self.updater.mk_assign(inst, x_op)
            return

        # range-based: if x is in the valid signed range for (n+1) bytes,
        # signextend is a no-op
        if not self._is_lit(n_op):
            return
        n = n_op.value
        if not (0 <= n < 31):
            return
        x_range = self.range_analysis.get_range(x_op, inst)
        if x_range.is_top:
            return
        bits = 8 * (n + 1)
        if x_range.lo >= -(1 << (bits - 1)) and x_range.hi <= (1 << (bits - 1)) - 1:
            self.updater.mk_assign(inst, x_op)

    def _rule_exp(self, inst: IRInstruction):
        ops = inst.operands
        # x ** 0 -> 1
        if lit_eq(ops[0], 0):
            self.updater.mk_assign(inst, IRLiteral(1))
        # 1 ** x -> 1
        elif lit_eq(ops[1], 1):
            self.updater.mk_assign(inst, IRLiteral(1))
        # 0 ** x -> iszero x
        elif lit_eq(ops[1], 0):
            self.updater.update(inst, "iszero", [ops[0]])
        # x ** 1 -> x
        elif lit_eq(ops[0], 1):
            self.updater.mk_assign(inst, ops[1])

    def _rule_gep(self, inst: IRInstruction):
        if lit_eq(inst.operands[1], 0):
            self.updater.mk_assign(inst, inst.operands[0])

    def _rule_additive(self, inst: IRInstruction):
        ops = inst.operands
        opcode = inst.opcode

        # (x - x) == (x ^ x) == 0
        if opcode in ("xor", "sub") and ops[0] == ops[1]:
            self.updater.mk_assign(inst, IRLiteral(0))
            return

        # x + 0, x - 0, x ^ 0 -> x
        if lit_eq(ops[0], 0):
            self.updater.mk_assign(inst, ops[1])
            return

        # (-1) - x -> ~x
        if opcode == "sub" and lit_eq(ops[1], -1):
            self.updater.update(inst, "not", [ops[0]])
            return

        # x ^ -1 -> ~x
        if opcode == "xor" and lit_eq(ops[0], -1):
            self.updater.update(inst, "not", [ops[1]])

    def _rule_and(self, inst: IRInstruction):
        ops = inst.operands
        # x & -1 -> x
        if lit_eq(ops[0], -1):
            self.updater.mk_assign(inst, ops[1])
            return
        # x & 0 -> 0
        if any(lit_eq(op, 0) for op in ops):
            self.updater.mk_assign(inst, IRLiteral(0))

    def _rule_multiplicative(self, inst: IRInstruction):
        ops = inst.operands
        opcode = inst.opcode

        # x * 0, x / 0, x % 0 -> 0
        if any(lit_eq(op, 0) for op in ops):
            self.updater.mk_assign(inst, IRLiteral(0))
            return

        # x % 1 -> 0
        if opcode in ("mod", "smod") and lit_eq(ops[0], 1):
            self.updater.mk_assign(inst, IRLiteral(0))
            return

        # x * 1, x / 1 -> x
        if opcode in ("mul", "div", "sdiv") and lit_eq(ops[0], 1):
            self.updater.mk_assign(inst, ops[1])
            return

        # power-of-two strength reduction
        if not (self._is_lit(ops[0]) and is_power_of_two(ops[0].value)):
            return
        val = ops[0].value
        if opcode == "mod":
            self.updater.update(inst, "and", [IRLiteral(val - 1), ops[1]])
        elif opcode == "div":
            self.updater.update(inst, "shr", [ops[1], IRLiteral(int_log2(val))])
        elif opcode == "mul":
            self.updater.update(inst, "shl", [ops[1], IRLiteral(int_log2(val))])

    def _rule_or(self, inst: IRInstruction):
        ops = inst.operands
        # x | -1 -> -1
        if any(lit_eq(op, SizeLimits.MAX_UINT256) for op in ops):
            self.updater.mk_assign(inst, IRLiteral(SizeLimits.MAX_UINT256))
            return

        # x | n -> 1 in truthy positions (if n != 0)
        uses = self.dfg.get_uses(inst.output)
        is_truthy = all(i.opcode in TRUTHY_INSTRUCTIONS for i in uses)
        if is_truthy and self._is_lit(ops[0]) and ops[0].value != 0:
            self.updater.mk_assign(inst, IRLiteral(1))
            return

        # x | 0 -> x
        if lit_eq(ops[0], 0):
            self.updater.mk_assign(inst, ops[1])

    def _rule_eq(self, inst: IRInstruction):
        ops = inst.operands
        # x == x -> 1
        if ops[0] == ops[1]:
            self.updater.mk_assign(inst, IRLiteral(1))
            return

        # x == 0 -> iszero x
        if lit_eq(ops[0], 0):
            self.updater.update(inst, "iszero", [ops[1]])
            return

        # eq x -1 -> iszero(~x)
        if lit_eq(ops[0], -1):
            var = self.updater.add_before(inst, "not", [ops[1]])
            assert var is not None
            self.updater.update(inst, "iszero", [var])
            return

        # in prefer_iszero context: eq x y -> iszero(xor x y)
        uses = self.dfg.get_uses(inst.output)
        if all(i.opcode in ("assert", "iszero") for i in uses):
            tmp = self.updater.add_before(inst, "xor", [ops[0], ops[1]])
            assert tmp is not None
            self.updater.update(inst, "iszero", [tmp])

    # --- Unchanged methods ---

    def _handle_offset(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if (
                    inst.opcode == "add"
                    and self._is_lit(inst.operands[0])
                    and isinstance(inst.operands[1], IRLabel)
                ):
                    inst.opcode = "offset"

    @staticmethod
    def _is_lit(operand: IROperand) -> bool:
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

    def _try_range_cmp(
        self, inst: IRInstruction, operands: list, is_gt: bool, signed: bool
    ) -> int | None:
        """Try to resolve a comparison to a constant using range analysis.
        Returns 0 or 1 if resolved, None otherwise."""
        a_op = operands[-1]  # first in text
        b_op = operands[-2]  # second in text

        # identify which operand is the literal and which is the variable
        if self._is_lit(a_op) and not self._is_lit(b_op):
            lit_val, var_op = a_op.value, b_op
            lit_is_first = True
        elif self._is_lit(b_op) and not self._is_lit(a_op):
            lit_val, var_op = b_op.value, a_op
            lit_is_first = False
        else:
            return None

        var_range = self.range_analysis.get_range(var_op, inst)
        if var_range.is_top or var_range.is_empty:
            return None

        # normalize literal to match range representation
        if signed:
            if var_range.hi > SizeLimits.MAX_INT256:
                return None
            lit_val = wrap256(lit_val, signed=True)
        else:
            if var_range.lo < 0:
                return None
            lit_val = wrap256(lit_val)

        # determine effective comparison direction:
        # lit_is_first with is_gt means "lit > var"
        # lit_is_first without is_gt means "lit < var"
        # flipping lit_is_first flips the direction
        lit_gt_var = is_gt == lit_is_first

        if lit_gt_var:
            # lit > var: always true if lit > var.hi, always false if lit <= var.lo
            if lit_val > var_range.hi:
                return 1
            if lit_val <= var_range.lo:
                return 0
        else:
            # var > lit: always true if var.lo > lit, always false if var.hi <= lit
            if var_range.lo > lit_val:
                return 1
            if var_range.hi <= lit_val:
                return 0

        return None

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

        # Range-based comparison optimization.
        # Try to resolve comparisons with one literal operand using
        # range analysis on the other.
        result = self._try_range_cmp(inst, operands, is_gt, signed)
        if result is not None:
            self.updater.mk_assign(inst, IRLiteral(result))
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
            if never == 0:
                # eq x 0 => iszero x
                self.updater.update(inst, "iszero", [operands[1]])
                return
            if wrap256(never) == wrap256(-1):
                # eq x -1 => iszero(not x)
                var = self.updater.add_before(inst, "not", [operands[1]])
                assert var is not None
                self.updater.update(inst, "iszero", [var])
                return
            self.updater.update(inst, "eq", [operands[1], IRLiteral(never)])
            return

        # rewrites. in positions where iszero is preferred, (gt x 5) => (ge x 6)
        if prefer_iszero and lit_eq(operands[0], almost_always):
            # e.g. gt x 0, slt x MAX_INT256
            # produce iszero(iszero(xor x N)) directly, with
            # xor x 0 = x and xor x -1 = not x as special cases
            val = wrap256(operands[0].value)
            x = operands[1]
            if val == 0:
                inner = x
            elif val == wrap256(-1):
                inner = self.updater.add_before(inst, "not", [x])
            else:
                inner = self.updater.add_before(inst, "xor", [operands[0], x])
            tmp = self.updater.add_before(inst, "iszero", [inner])
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
