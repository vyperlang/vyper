from vyper.exceptions import CompilerPanic
from vyper.utils import int_bounds, int_log2, is_power_of_two
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLabel, IRLiteral, IROperand, IRVariable
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.sccp.eval import signed_to_unsigned, unsigned_to_signed

COMPARISON_OPS = {"gt", "sgt", "lt", "slt"}


def _flip_comparison_op(opname):
    assert opname in COMPARISON_OPS
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


class AlgebraicOptimizationPass(IRPass):
    """
    This pass reduces algebraic evaluatable expressions.

    It currently optimizes:
        * iszero chains
    """

    dfg: DFGAnalysis

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

    def _update(
        self, inst: IRInstruction, opcode: str, *args: IROperand | int, force: bool = False
    ) -> bool:
        assert opcode != "phi"
        if not force and inst.opcode == opcode:
            return False

        for op in inst.operands:
            if isinstance(op, IRVariable):
                uses = self.dfg.get_uses(op)
                if inst in uses:
                    uses.remove(inst)
        inst.opcode = opcode
        inst.operands = [arg if isinstance(arg, IROperand) else IRLiteral(arg) for arg in args]

        for op in inst.operands:
            if isinstance(op, IRVariable):
                self.dfg.add_use(op, inst)

        return True

    def _store(self, inst: IRInstruction, *args: IROperand | int) -> bool:
        return self._update(inst, "store", *args)

    def _add(self, inst: IRInstruction, opcode: str, *args: IROperand | int) -> IRVariable:
        assert opcode != "phi"
        index = inst.parent.instructions.index(inst)
        var = inst.parent.parent.get_next_variable()
        operands = [arg if isinstance(arg, IROperand) else IRLiteral(arg) for arg in args]
        new_inst = IRInstruction(opcode, operands, output=var)
        inst.parent.insert_instruction(new_inst, index)
        for op in new_inst.operands:
            if isinstance(op, IRVariable):
                self.dfg.add_use(op, new_inst)
        self.dfg.add_use(var, inst)
        self.dfg.set_producing_instruction(var, new_inst)
        return var

    def _is_lit(self, operand: IROperand) -> bool:
        return isinstance(operand, IRLiteral)

    def _lit_eq(self, operand: IROperand, val: int) -> bool:
        return self._is_lit(operand) and operand.value == val

    def _op_eq(self, operands, idx_a: int, idx_b: int) -> bool:
        if self._is_lit(operands[idx_a]) and self._is_lit(operands[idx_b]):
            return operands[idx_a].value == operands[idx_b].value
        else:
            return operands[idx_a] == operands[idx_b]

    def _algebraic_opt(self):
        self.last = False
        self._algebraic_opt_pass()
        self.last = True
        self._algebraic_opt_pass()

    def _algebraic_opt_pass(self) -> bool:
        change = False
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if self._handle_inst_peephole(inst):
                    change |= True

        return change

    def _handle_inst_peephole(self, inst: IRInstruction) -> bool:
        if inst.opcode == "assert":
            return self.handle_assert_inst(inst)
        if inst.output is None:
            return False
        if inst.is_volatile:
            return False
        if inst.opcode == "store":
            return False
        if inst.is_pseudo:
            return False

        operands = inst.operands

        if (
            inst.opcode == "add"
            and self._is_lit(operands[0])
            and isinstance(inst.operands[1], IRLabel)
        ):
            inst.opcode = "offset"
            return True

        if inst.is_commutative and self._is_lit(operands[1]):
            operands = [operands[1], operands[0]]

        if inst.opcode in {"shl", "shr", "sar"}:
            if self._lit_eq(operands[1], 0):
                return self._store(inst, operands[0])
            # no more cases for these instructions
            return False

        if inst.opcode in {"add", "sub", "xor"}:
            # x + 0 == x - 0 == x ^ 0 -> x
            if self._lit_eq(operands[0], 0):
                return self._store(inst, operands[1])
            # -1 - x -> ~x
            # from two's compliment
            if inst.opcode == "sub" and self._lit_eq(operands[1], -1):
                return self._update(inst, "not", operands[0])
            # x ^ -1 -> ~x
            if inst.opcode == "xor" and self._lit_eq(operands[0], signed_to_unsigned(-1, 256)):
                return self._update(inst, "not", operands[1])
            return False

        if inst.opcode in {"mul", "div", "sdiv", "mod", "smod", "and"}:
            # x * 1 == x / 1 -> x
            if inst.opcode in {"mul", "div", "sdiv"} and self._lit_eq(operands[0], 1):
                return self._store(inst, operands[1])

            # x & 0xFF..FF -> x
            if inst.opcode == "and" and self._lit_eq(operands[0], signed_to_unsigned(-1, 256)):
                return self._store(inst, operands[1])

            if self._is_lit(operands[0]) and is_power_of_two(operands[0].value):
                val = operands[0].value
                # x % (2^n) -> x & (2^n - 1)
                if inst.opcode == "mod":
                    return self._update(inst, "and", val - 1, operands[1])
                # x / (2^n) -> x >> n
                if inst.opcode == "div":
                    return self._update(inst, "shr", operands[1], int_log2(val))
                # x * (2^n) -> x << n
                if inst.opcode == "mul":
                    return self._update(inst, "shl", operands[1], int_log2(val))
            return False

        if inst.opcode == "exp":
            # 0 ** x -> iszero x
            if self._lit_eq(operands[1], 0):
                return self._update(inst, "iszero", operands[0])

            # x ** 1 -> x
            if self._lit_eq(operands[0], 1):
                return self._store(inst, operands[1])

            return False

        if inst.opcode not in COMPARISON_OPS and inst.opcode not in {"eq", "or"}:
            return False

        # x | 0 -> x
        if inst.opcode == "or" and self._lit_eq(operands[0], 0):
            return self._store(inst, operands[1])

        # x | 0xFF..FF ->  0xFF..FF
        if inst.opcode == "or" and self._lit_eq(operands[0], signed_to_unsigned(-1, 256)):
            return self._store(inst, signed_to_unsigned(-1, 256))

        # x == 0 -> iszero x
        if inst.opcode == "eq" and self._lit_eq(operands[0], 0):
            return self._update(inst, "iszero", operands[1])

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
                tmp = self._add(inst, "xor", operands[0], operands[1])

                return self._update(inst, "iszero", tmp)

            # x | n -> 1 (if n is non zero)
            if inst.opcode == "or" and self._is_lit(operands[0]) and operands[0].value != 0:
                return self._store(inst, 1)

        if inst.opcode in COMPARISON_OPS:
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

            if self._is_lit(operands[0]) and operands[0].value == almost_never:
                # (lt x 1), (gt x (MAX_UINT256 - 1)), (slt x (MIN_INT256 + 1))
                return self._update(inst, "eq", operands[1], never)

            # rewrites. in positions where iszero is preferred, (gt x 5) => (ge x 6)
            if (
                not prefer_strict
                and self._is_lit(operands[0])
                and operands[0].value == almost_always
            ):
                # e.g. gt x 0, slt x MAX_INT256
                tmp = self._add(inst, "eq", *operands)
                return self._update(inst, "iszero", tmp)

            # special cases that are not covered by others:

            if opcode == "gt" and self._is_lit(operands[0]) and operands[0].value == 0:
                # improve codesize (not gas), and maybe trigger
                # downstream optimizations
                tmp = self._add(inst, "iszero", operands[1])
                return self._update(inst, "iszero", tmp)

            # only done in last iteration because on average if not already optimize
            # this rule creates bigger codesize because it could interfere with other
            # optimizations
            if (
                self.last
                and len(uses) == 1
                and uses.first().opcode == "iszero"
                and self._is_lit(operands[0])
            ):
                after = uses.first()
                n_uses = self.dfg.get_uses(after.output)
                if len(n_uses) != 1 or n_uses.first().opcode in ["iszero", "assert"]:
                    return False

                n_op = operands[0].value
                if "gt" in opcode:
                    n_op += 1
                else:
                    n_op -= 1

                assert _wrap256(n_op, unsigned) == n_op, "bad optimizer step"
                n_opcode = _flip_comparison_op(inst.opcode)
                self._update(inst, n_opcode, n_op, operands[1], force=True)
                uses.first().opcode = "store"
                return True

        return False

    def handle_assert_inst(self, inst: IRInstruction) -> bool:
        operands = inst.operands
        if not isinstance(operands[0], IRVariable):
            return False
        src = self.dfg.get_producing_instruction(operands[0])
        assert isinstance(src, IRInstruction)
        if src.opcode not in COMPARISON_OPS:
            return False

        assert isinstance(src.output, IRVariable)
        uses = self.dfg.get_uses(src.output)
        if len(uses) != 1:
            return False

        if not isinstance(src.operands[0], IRLiteral):
            return False

        n_op = src.operands[0].value
        if "gt" in src.opcode:
            n_op += 1
        else:
            n_op -= 1
        unsigned = "s" not in src.opcode

        assert _wrap256(n_op, unsigned) == n_op, "bad optimizer step"
        n_opcode = _flip_comparison_op(src.opcode)

        src.opcode = n_opcode
        src.operands = [IRLiteral(n_op), src.operands[1]]

        var = self._add(inst, "iszero", src.output)
        self.dfg.add_use(var, inst)

        self._update(inst, "assert", var, force=True)

        return True

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)  # type: ignore

        self._optimize_iszero_chains()
        self._algebraic_opt()

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
