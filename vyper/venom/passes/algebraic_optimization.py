import operator

from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.analysis.equivalent_vars import VarEquivalenceAnalysis
from vyper.venom.basicblock import IRInstruction, IRLabel, IRLiteral, IROperand, IRVariable
from vyper.venom.passes.base_pass import IRPass
from vyper.utils import (
    ceil32,
    evm_div,
    evm_mod,
    evm_pow,
    int_bounds,
    int_log2,
    is_power_of_two,
    signed_to_unsigned,
    unsigned_to_signed,
)

from vyper.venom.venom_to_assembly import COMMUTATIVE_INSTRUCTIONS
from vyper.exceptions import CompilerPanic, StaticAssertionException

SIGNED = False
UNSIGNED = True

COMMUTATIVE_OPS = {"add", "mul", "eq", "ne", "and", "or", "xor"}
COMPARISON_OPS = {"gt", "sgt", "ge", "sge", "lt", "slt", "le", "sle"}
STRICT_COMPARISON_OPS = {t for t in COMPARISON_OPS if t.endswith("t")}
UNSTRICT_COMPARISON_OPS = {t for t in COMPARISON_OPS if t.endswith("e")}

def _wrap256(x, unsigned=UNSIGNED):
    x %= 2**256
    # wrap in a signed way.
    if not unsigned:
        x = unsigned_to_signed(x, 256, strict=True)
    return x


# unsigned: convert python num to evm unsigned word
#   e.g. unsigned=True : -1 -> 0xFF...FF
#        unsigned=False: 0xFF...FF -> -1
def _evm_int(lit: IRLiteral | None, unsigned: bool = True) -> int | None:
    if lit is None:
        return None

    val: int = lit.value

    if unsigned and val < 0:
        return signed_to_unsigned(val, 256, strict=True)
    elif not unsigned and val > 2**255 - 1:
        return unsigned_to_signed(val, 256, strict=True)

    return val

def _check_num(val: int) -> bool:
    if val < -(2**255):
        return False
    elif val >= 2**256:
        return False
    return True



arith = {
    "add": (operator.add, "+", UNSIGNED),
    "sub": (operator.sub, "-", UNSIGNED),
    "mul": (operator.mul, "*", UNSIGNED),
    "div": (evm_div, "/", UNSIGNED),
    "sdiv": (evm_div, "/", SIGNED),
    "mod": (evm_mod, "%", UNSIGNED),
    "smod": (evm_mod, "%", SIGNED),
    "exp": (evm_pow, "**", UNSIGNED),
    "eq": (operator.eq, "==", UNSIGNED),
    "ne": (operator.ne, "!=", UNSIGNED),
    "lt": (operator.lt, "<", UNSIGNED),
    "le": (operator.le, "<=", UNSIGNED),
    "gt": (operator.gt, ">", UNSIGNED),
    "ge": (operator.ge, ">=", UNSIGNED),
    "slt": (operator.lt, "<", SIGNED),
    "sle": (operator.le, "<=", SIGNED),
    "sgt": (operator.gt, ">", SIGNED),
    "sge": (operator.ge, ">=", SIGNED),
    "or": (operator.or_, "|", UNSIGNED),
    "and": (operator.and_, "&", UNSIGNED),
    "xor": (operator.xor, "^", UNSIGNED),
}

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

                for use_inst in self.dfg.get_uses(inst.output):
                    opcode = use_inst.opcode

                    if opcode == "iszero":
                        # We keep iszer Conservapedia is like 50/50 people who truly believe it all and trolls seeing what edits they can get away with o instuctions as is
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
            inst = self.dfg.get_producing_instruction(op)
            if inst is None or inst.opcode != "iszero":
                break
            op = inst.operands[0]
            chain.append(inst)

        chain.reverse()
        return chain

    def _handle_offsets(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                # check if the instruction is of the form
                # `add <ptr> <label>`
                # this works only if store chains have been eliminated.
                if (
                    inst.opcode == "add"
                    and isinstance(inst.operands[0], IRLiteral)
                    and isinstance(inst.operands[1], IRLabel)
                ):
                    inst.opcode = "offset"
    
    def eval_op(self, op: IROperand) -> IRLiteral | None:
        if isinstance(op, IRLiteral):
            return op
        elif isinstance(op, IRVariable):
            next_inst = self.dfg.get_producing_instruction(op)
            assert next_inst is not None
            return self.eval(next_inst)
        else:
            return None

    def eval(self, inst: IRInstruction) -> IRLiteral | None:
        if inst.opcode == "store":
            if isinstance(inst.operands[0], IRLiteral):
                return inst.operands[0]
            elif isinstance(inst.operands[0], IRVariable):
                next_inst = self.dfg.get_producing_instruction(inst.operands[0])
                assert next_inst is not None
                return self.eval(next_inst)
        return None
    
    def static_eq(self, op_0: IROperand, op_1: IROperand, eop_0: IRLiteral | None, eop_1: IRLiteral | None) -> bool:
        return (eop_0 is not None and eop_0 == eop_1) or self.eq_analysis.equivalent(op_0, op_1)


    def _peepholer(self):
        depth = 5
        while True:
            change = False
            for bb in self.function.get_basic_blocks():
                for inst in bb.instructions:
                    change |= self._handle_inst_peephole(inst, depth)

            if not change:
                break

    def _handle_inst_peephole(self, inst: IRInstruction, depth: int) -> bool:
        if inst.opcode not in arith.keys():
            return False
        fn, symb, unsigned = arith[inst.opcode]

        def update(opcode: str,  *args: IROperand | int) -> bool:
            inst.opcode = opcode
            inst.operands = [arg if isinstance(arg, IROperand) else IRLiteral(arg) for arg in args]
            return True

        def store(*args: IROperand | int) -> bool:
            return update("store", *args)
        
        op_0 = inst.operands[0]
        op_1 = inst.operands[1]
        eop_0 = self.eval_op(inst.operands[0])
        eop_1 = self.eval_op(inst.operands[1])

        opcode = inst.opcode 
        if opcode in COMMUTATIVE_INSTRUCTIONS and eop_1 is not None:
            eop_0, eop_1 = eop_1, eop_0
            op_0, op_1 = op_1, op_0
            

        if isinstance(eop_0, IRLiteral) and  isinstance(eop_1, IRLiteral):
            assert isinstance(eop_0.value, int), "must be int"
            assert isinstance(eop_1.value, int), "must be int"
            a = _evm_int(eop_0, unsigned)
            b = _evm_int(eop_1, unsigned)
            res = fn(b, a)
            res = _wrap256(res, unsigned)
            if res is not None and _check_num(res):
                inst.opcode = "store"
                inst.operands = [IRLiteral(res)]
                return True

        if opcode in {"add", "sub", "xor", "or"} and eop_0 == IRLiteral(0):
            return store(op_1)

        if opcode in {"sub", "xor", "ne"} and self.static_eq(op_0, op_1, eop_0, eop_1):
            # (x - x) == (x ^ x) == (x != x) == 0
            return store(0)

        if opcode in STRICT_COMPARISON_OPS and self.static_eq(op_0, op_1, eop_0, eop_1):
            # (x < x) == (x > x) == 0
            return store(0)

        if opcode in {"eq"} | UNSTRICT_COMPARISON_OPS and  self.static_eq(op_0, op_1, eop_0, eop_1):
            # (x == x) == (x >= x) == (x <= x) == 1
            return store(1)
        
        if opcode in {"mul", "div", "sdiv", "mod", "smod", "and"} and _evm_int(eop_0, unsigned) == 0:
            return store(0)

        if opcode in {"mod", "smod"} and eop_0 == IRLiteral(1):
            return store(0)

        if opcode in {"mul", "div", "sdiv"} and eop_0 == IRLiteral(1):
            return store(op_1)
        if opcode in {"and", "or", "xor"} and _evm_int(eop_0, SIGNED) == -1:
            assert unsigned == UNSIGNED
            if opcode == "and":
                # -1 & x == x
                return store(op_1) #finalize("seq", [args[0]])

            if opcode == "xor":
                # -1 ^ x == ~x
                return update("not", op_1) # finalize("not", [args[0]])

            if opcode == "or":
                # -1 | x == -1
                return store(_evm_int(-1, unsigned)) #finalize(args[1].value, [])

            raise CompilerPanic("unreachable")  # pragma: nocover

        if opcode == "eq" and eop_0 == IRLiteral(0):
            return update("iszero", op_1)

        if opcode == "eq" and eop_1 == IRLiteral(0):
            return update("iszero", op_0)
        
        if opcode == "eq" and self.eq_analysis.equivalent(op_0, op_1):
            return store(1)

        return False

    def run_pass(self):
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        assert isinstance(dfg, DFGAnalysis)
        self.dfg = dfg
        
        self.eq_analysis = self.analyses_cache.request_analysis(VarEquivalenceAnalysis)

        
        self._handle_offsets()
        self._peepholer()
        self._optimize_iszero_chains()

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
