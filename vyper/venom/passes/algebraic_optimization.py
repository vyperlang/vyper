from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLabel, IRLiteral, IROperand, IRVariable
from vyper.venom.passes.base_pass import IRPass


class _InstTree:
    inst: IRInstruction
    operands: list["IROperand | _InstTree"]

    def __init__(self, inst: IRInstruction, operands: list["IROperand | _InstTree"]) -> None:
        self.inst = inst
        self.operands = operands
    
    @property
    def opcode(self) -> str:
        return self.inst.opcode
    
    def eval_to(self, val: IRLiteral) -> bool:
        if self.opcode == "store":
            if isinstance(self.operands[0], IRLiteral):
                return self.operands[0] == val
            elif isinstance(self.operands[0], _InstTree):
                return self.operands[0].eval_to(val)
        return False

    def op_eval_to(self, index: int, val: IRLiteral) -> bool:
        op = self.operands[index]
        if isinstance(op, IRLiteral):
            return op == val
        elif isinstance(op, _InstTree):
            return op.eval_to(val)
        else:
            return False

class AlgebraicOptimizationPass(IRPass):
    """
    This pass reduces algebraic evaluatable expressions.

    It currently optimizes:
        * iszero chains
    """

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
    
    def _get_tree_op(self, op: IROperand, depth) -> IROperand | _InstTree:
        if depth == 0 or not isinstance(op, IRVariable):
            return op
        inst = self.dfg.get_producing_instruction(op)
        assert isinstance(inst, IRInstruction)
        return self._get_tree(inst, depth - 1)

    def _get_tree(self, inst: IRInstruction, depth: int = 0) -> _InstTree:
        return _InstTree(inst, [self._get_tree_op(op, depth) for op in inst.operands])
        
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
        inst_tree = self._get_tree(inst, depth)
        
        if inst_tree.opcode in {"add", "sub", "xor", "or"} and inst_tree.op_eval_to(0, IRLiteral(0)):
            inst_tree.inst.opcode = "store"
            inst_tree.inst.operands = [inst.operands[1]]
            return True
        
        if inst_tree.opcode in {"mul", "div", "sdiv", "mod", "smod", "and"} and inst_tree.op_eval_to(0, IRLiteral(0)):
            inst_tree.inst.opcode = "store"
            inst_tree.inst.operands = [IRLiteral(0)]
            return True

        if inst_tree.opcode in {"mod", "smod"} and inst_tree.op_eval_to(0, IRLiteral(1)):
            inst_tree.inst.opcode = "store"
            inst_tree.inst.operands = [IRLiteral(0)]
            return True

        if inst_tree.opcode in {"mul", "div", "sdiv"} and inst_tree.op_eval_to(0, IRLiteral(1)):
            inst_tree.inst.opcode = "store"
            inst_tree.inst.operands = [inst.operands[1]]
            return True

        if inst_tree.op_eval_to == "eq" and inst_tree.op_eval_to(0, IRLiteral(0)):
            inst_tree.inst.opcode = "iszero"
            inst_tree.inst.operands = [inst.operands[1]]
            return True

        if inst_tree.op_eval_to == "eq" and inst_tree.op_eval_to(1, IRLiteral(0)):
            inst_tree.inst.opcode = "iszero"
            inst_tree.inst.operands = [inst.operands[0]]
            return True

        return False

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self._optimize_iszero_chains()
        self._handle_offsets()
        self._peepholer()

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
