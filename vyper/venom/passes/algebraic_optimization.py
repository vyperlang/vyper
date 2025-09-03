from vyper.utils import SizeLimits, int_bounds, int_log2, is_power_of_two, wrap256
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
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


class AlgebraicOptimizationPass(IRPass):
    """
    This pass reduces algebraic evaluatable expressions.

    It currently optimizes:
      - iszero chains
      - binops
      - offset adds
    """

    dfg: DFGAnalysis
    updater: InstUpdater

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self._handle_offset()

        self._algebraic_opt()
        self._optimize_iszero_chains()
        self._algebraic_opt()

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
                for use_inst in self.dfg.get_uses(inst.output).copy():
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
                    self.updater.update_operands(use_inst, {inst.output: out_var})

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

    def _algebraic_opt_pass(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                self._handle_inst_peephole(inst)
                self._flip_inst(inst)

    def _flip_inst(self, inst: IRInstruction):
        ops = inst.operands
        # improve code. this seems like it should be properly handled by
        # better heuristics in DFT pass.
        if inst.flippable and self._is_lit(ops[0]) and not self._is_lit(ops[1]):
            inst.flip()

    # "peephole", weakening algebraic optimizations
    def _handle_inst_peephole(self, inst: IRInstruction):
        if inst.output is None:
            return
        if inst.is_volatile:
            return
        if inst.opcode == "assign":
            return
        if inst.is_pseudo:
            return

        # TODO nice to have rules:
        # -1 * x => 0 - x
        # x // -1 => 0 - x (?)
        # x + (-1) => x - 1  # save codesize, maybe for all negative numbers)
        # 1 // x => x == 1(?)
        # 1 % x => x > 1(?)
        # !!x => x > 0  # saves 1 gas as of shanghai

        operands = inst.operands

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

        assert inst.output is not None
        uses = self.dfg.get_uses(inst.output)

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

    def _optimize_comparator_instruction(self, inst, prefer_iszero):
        opcode, operands = inst.opcode, inst.operands
        assert opcode in COMPARATOR_INSTRUCTIONS  # sanity
        assert isinstance(inst.output, IRVariable)  # help mypy

        # (x > x) == (x < x) -> 0
        if operands[0] == operands[1]:
            self.updater.mk_assign(inst, IRLiteral(0))
            return

        is_gt = "g" in opcode
        signed = "s" in opcode

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
        assert inst.output is not None
        uses = self.dfg.get_uses(inst.output)
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
            assert inst.output is not None, inst
            assert len(after.operands) == 1, after
            var = self.updater.add_before(after, "iszero", [inst.output])
            self.updater.update_operands(after, {after.operands[0]: var})
        else:
            # remove the iszero!
            assert len(after.operands) == 1, after
            self.updater.update(after, "assign", after.operands)
