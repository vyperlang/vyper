from typing import Optional

from vyper.exceptions import CompilerPanic
from vyper.utils import int_bounds, int_log2, is_power_of_two
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import (
    COMPARATOR_INSTRUCTIONS,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.sccp.eval import lit_eq, signed_to_unsigned, unsigned_to_signed


def _flip_comparison_op(opname):
    assert opname in COMPARATOR_INSTRUCTIONS
    if "g" in opname:
        return opname.replace("g", "l")
    if "l" in opname:
        return opname.replace("l", "g")
    raise CompilerPanic(f"bad comparison op {opname}")  # pragma: nocover


def _wrap256(x, unsigned: bool):
    x %= 2**256
    # wrap in a signed way.
    if not unsigned:
        x = unsigned_to_signed(x, 256, strict=True)
    return x


class InstructionUpdater:
    """
    A helper class for updating instructions which also updates the
    basic block and dfg in place
    """

    def __init__(self, dfg: DFGAnalysis):
        self.dfg = dfg

    def _update_operands(self, inst: IRInstruction, replace_dict: dict[IROperand, IROperand]):
        old_operands = inst.operands
        new_operands = [replace_dict[op] if op in replace_dict else op for op in old_operands]
        self._update(inst, inst.opcode, new_operands)

    def _update(self, inst: IRInstruction, opcode: str, args: list[IROperand]):
        assert opcode != "phi"

        old_operands = inst.operands
        new_operands = list(args)

        for op in old_operands:
            if not isinstance(op, IRVariable):
                continue
            uses = self.dfg.get_uses(op)
            if inst in uses:
                uses.remove(inst)

        for op in new_operands:
            if isinstance(op, IRVariable):
                self.dfg.add_use(op, inst)

        inst.opcode = opcode
        inst.operands = new_operands

    def _store(self, inst: IRInstruction, op: IROperand):
        self._update(inst, "store", [op])

    def _add_before(self, inst: IRInstruction, opcode: str, args: list[IROperand]) -> IRVariable:
        """
        Insert another instruction before the given instruction
        """
        assert opcode != "phi"
        index = inst.parent.instructions.index(inst)
        var = inst.parent.parent.get_next_variable()
        operands = list(args)
        new_inst = IRInstruction(opcode, operands, output=var)
        inst.parent.insert_instruction(new_inst, index)
        for op in new_inst.operands:
            if isinstance(op, IRVariable):
                self.dfg.add_use(op, new_inst)
        self.dfg.add_use(var, inst)
        self.dfg.set_producing_instruction(var, new_inst)
        return var


class AlgebraicOptimizationPass(IRPass):
    """
    This pass reduces algebraic evaluatable expressions.

    It currently optimizes:
      - iszero chains
      - binops
      - offset adds
    """

    dfg: DFGAnalysis
    updater: InstructionUpdater

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)  # type: ignore
        self.updater = InstructionUpdater(self.dfg)

        self._optimize_iszero_chains()

        self._handle_offset()
        self._algebraic_opt()

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

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

                assert isinstance(inst.output, IRVariable)
                for use_inst in self.dfg.get_uses(inst.output):
                    opcode = use_inst.opcode

                    if opcode == "iszero":
                        # We keep iszero instuctions as is
                        continue
                    if opcode in ("jnz", "assert"):
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
                    use_inst.replace_operands({inst.output: out_var})

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

    def _algebraic_opt(self):
        self._algebraic_opt_pass()
        self._algebraic_opt_ge_le()

    def _algebraic_opt_pass(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                self._handle_inst_peephole(inst)

    def _algebraic_opt_ge_le(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode in COMPARATOR_INSTRUCTIONS:
                    self._handle_inst_ge_le(inst)

    def _handle_inst_peephole(self, inst: IRInstruction):
        if inst.opcode == "assert":
            self._handle_assert_inst(inst)
            return
        if inst.output is None:
            return
        if inst.is_volatile:
            return
        if inst.opcode == "store":
            return
        if inst.is_pseudo:
            return

        operands = inst.operands

        # make logic easier for commutative instructions.
        if inst.is_commutative and self._is_lit(operands[1]):
            operands = [operands[1], operands[0]]

        if inst.opcode in {"shl", "shr", "sar"}:
            if lit_eq(operands[1], 0):
                self.updater._store(inst, operands[0])
                return
            # no more cases for these instructions
            return

        if inst.opcode in {"add", "sub", "xor"}:
            # x + 0 == x - 0 == x ^ 0 -> x
            if lit_eq(operands[0], 0):
                self.updater._store(inst, operands[1])
                return
            # -1 - x -> ~x
            # from two's compliment
            if inst.opcode == "sub" and lit_eq(operands[1], -1):
                self.updater._update(inst, "not", [operands[0]])
                return
            # x ^ -1 -> ~x
            if inst.opcode == "xor" and lit_eq(operands[0], signed_to_unsigned(-1, 256)):
                self.updater._update(inst, "not", [operands[1]])
                return
            return

        # TODO rules like:
        # not x | not y => not (x & y)
        # x | not y => not (not x & y)

        # x | 0 -> x
        if inst.opcode == "or" and lit_eq(operands[0], 0):
            self.updater._store(inst, operands[1])
            return

        # x & 0xFF..FF -> x
        if inst.opcode == "and" and lit_eq(operands[0], signed_to_unsigned(-1, 256)):
            self.updater._store(inst, operands[1])
            return

        if inst.opcode in {"mul", "div", "sdiv", "mod", "smod"}:
            # x * 1 == x / 1 -> x
            if inst.opcode in {"mul", "div", "sdiv"} and lit_eq(operands[0], 1):
                self.updater._store(inst, operands[1])
                return

            if self._is_lit(operands[0]) and is_power_of_two(operands[0].value):
                val = operands[0].value
                # x % (2^n) -> x & (2^n - 1)
                if inst.opcode == "mod":
                    self.updater._update(inst, "and", [IRLiteral(val - 1), operands[1]])
                    return
                # x / (2^n) -> x >> n
                if inst.opcode == "div":
                    self.updater._update(inst, "shr", [operands[1], IRLiteral(int_log2(val))])
                    return
                # x * (2^n) -> x << n
                if inst.opcode == "mul":
                    self.updater._update(inst, "shl", [operands[1], IRLiteral(int_log2(val))])
                    return
            return

        if inst.opcode == "exp":
            # 0 ** x -> iszero x
            if lit_eq(operands[1], 0):
                self.updater._update(inst, "iszero", [operands[0]])
                return

            # x ** 1 -> x
            if lit_eq(operands[0], 1):
                self.updater._store(inst, operands[1])
                return

            return

        if inst.opcode not in COMPARATOR_INSTRUCTIONS and inst.opcode not in {"eq", "or"}:
            return

        # x == 0 -> iszero x
        if inst.opcode == "eq":
            if lit_eq(operands[0], 0):
                self.updater._update(inst, "iszero", [operands[1]])
                return

            if lit_eq(operands[0], signed_to_unsigned(-1, 256)):
                var = self.updater._add_before(inst, "not", [operands[1]])
                self.updater._update(inst, "iszero", [var])
                return

        assert isinstance(inst.output, IRVariable), "must be variable"
        uses = self.dfg.get_uses(inst.output)
        is_truthy = all(i.opcode in ("assert", "iszero", "jnz") for i in uses)

        if is_truthy:
            if inst.opcode == "eq":
                # (eq x y) has the same truthyness as (iszero (xor x y))
                # it also has the same truthyness as (iszero (sub x y)),
                # but xor is slightly easier to optimize because of being
                # commutative.
                # note that (xor (-1) x) has its own rule
                tmp = self.updater._add_before(inst, "xor", [operands[0], operands[1]])

                self.updater._update(inst, "iszero", [tmp])
                return

            # TODO: move this rule to sccp (since it can affect control flow).
            # x | n -> 1 (if n is non zero)
            if inst.opcode == "or" and self._is_lit(operands[0]) and operands[0].value != 0:
                self.updater._store(inst, IRLiteral(1))
                return

        if inst.opcode in COMPARATOR_INSTRUCTIONS:
            prefer_strict = not is_truthy
            opcode = inst.opcode

            # can flip from x > y into x < y
            # if it could put the literal
            # into the first operand (for easier logic)
            if self._is_lit(operands[1]):
                opcode = _flip_comparison_op(inst.opcode)
                operands = [operands[1], operands[0]]

            is_gt = "g" in opcode

            unsigned = "s" not in opcode

            lo, hi = int_bounds(bits=256, signed=not unsigned)

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

            if lit_eq(operands[0], almost_never):
                # (lt x 1), (gt x (MAX_UINT256 - 1)), (slt x (MIN_INT256 + 1))
                self.updater._update(inst, "eq", [operands[1], IRLiteral(never)])
                return

            # rewrites. in positions where iszero is preferred, (gt x 5) => (ge x 6)
            if not prefer_strict and lit_eq(operands[0], almost_always):
                # e.g. gt x 0, slt x MAX_INT256
                tmp = self.updater._add_before(inst, "eq", operands)
                self.updater._update(inst, "iszero", [tmp])
                return

            # special cases that are not covered by others:
            if opcode == "gt" and lit_eq(operands[0], 0):
                # improve codesize (not gas) and maybe trigger
                # downstream optimizations
                tmp = self.updater._add_before(inst, "iszero", [operands[1]])
                self.updater._update(inst, "iszero", [tmp])
                return

    # rewrite comparisons by adding an `iszero`, e.g.
    # `x > N` -> `x >= (N + 1)`
    def _rewrite_comparison(self, opcode: str, operands: list[IROperand]) -> Optional[IRLiteral]:
        val = operands[0].value
        unsigned = "s" not in opcode
        if "gt" in opcode:
            val += 1
        else:
            val -= 1

        if not unsigned:
            val = signed_to_unsigned(val, 256)

        # this can happen for cases like `lt x 0` which get reduced in SCCP.
        # don't handle them here, just return
        if _wrap256(val, unsigned) != val:
            return None

        return IRLiteral(val)

    # do this rule after the other algebraic optimizations because
    # it could interfere with other optimizations
    def _handle_inst_ge_le(self, inst: IRInstruction):
        assert inst.opcode in COMPARATOR_INSTRUCTIONS
        assert isinstance(inst.output, IRVariable), "must be variable"
        uses = self.dfg.get_uses(inst.output)

        operands = inst.operands
        opcode = inst.opcode

        if self._is_lit(operands[1]):
            opcode = _flip_comparison_op(inst.opcode)
            operands = [operands[1], operands[0]]

        if not self._is_lit(operands[0]):
            return
        if len(uses) != 1:
            return

        after = uses.first()
        if not after.opcode == "iszero":
            return

        n_uses = self.dfg.get_uses(after.output)
        if len(n_uses) != 1 or n_uses.first().opcode == "assert":
            return

        val = self._rewrite_comparison(opcode, operands)
        if val is None:
            return
        new_opcode = _flip_comparison_op(opcode)

        self.updater._update(inst, new_opcode, [val, operands[1]])

        assert len(after.operands) == 1
        self.updater._update(after, "store", after.operands)

    def _handle_assert_inst(self, inst: IRInstruction):
        operands = inst.operands
        if not isinstance(operands[0], IRVariable):
            return
        src = self.dfg.get_producing_instruction(operands[0])
        assert isinstance(src, IRInstruction)
        if src.opcode not in COMPARATOR_INSTRUCTIONS:
            return

        assert isinstance(src.output, IRVariable)
        uses = self.dfg.get_uses(src.output)
        if len(uses) != 1:
            return

        operands = src.operands
        opcode = src.opcode

        if self._is_lit(operands[1]):
            opcode = _flip_comparison_op(src.opcode)
            operands = [operands[1], operands[0]]

        if not isinstance(src.operands[0], IRLiteral):
            return

        val = self._rewrite_comparison(opcode, src.operands)
        if val is None:
            return
        new_opcode = _flip_comparison_op(opcode)

        src.opcode = new_opcode
        src.operands = [val, operands[1]]

        var = self.updater._add_before(inst, "iszero", [src.output])

        self.updater._update(inst, inst.opcode, [var])

        return
