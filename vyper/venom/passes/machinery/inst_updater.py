from vyper.venom.analysis import DFGAnalysis
from vyper.venom.basicblock import NO_OUTPUT_INSTRUCTIONS, IRInstruction, IROperand, IRVariable


class InstUpdater:
    """
    A helper class for updating instructions which also updates the
    basic block and dfg in place
    """

    def __init__(self, dfg: DFGAnalysis):
        self.dfg = dfg

    def update_operands(self, inst: IRInstruction, replace_dict: dict[IROperand, IROperand]):
        old_operands = inst.operands
        new_operands = [replace_dict[op] if op in replace_dict else op for op in old_operands]
        self.update(inst, inst.opcode, new_operands)

    def update(self, inst: IRInstruction, opcode: str, new_operands: list[IROperand]):
        assert opcode != "phi"
        # sanity
        assert all(isinstance(op, IROperand) for op in new_operands)

        old_operands = inst.operands

        for op in old_operands:
            if not isinstance(op, IRVariable):
                continue
            uses = self.dfg.get_uses(op)
            uses.discard(inst)

        for op in new_operands:
            if isinstance(op, IRVariable):
                self.dfg.add_use(op, inst)

        if opcode in NO_OUTPUT_INSTRUCTIONS and inst.output is not None:
            assert len(uses := self.dfg.get_uses(inst.output)) == 0, (inst, uses)
            inst.output = None

        inst.opcode = opcode
        inst.operands = new_operands

    def nop(self, inst: IRInstruction, annotation: str = ""):
        inst.annotation = str(inst) + " " + annotation
        self.update(inst, "nop", [])

    def remove(self, inst: IRInstruction):
        self.nop(inst)  # for dfg updates and checks
        inst.parent.remove_instruction(inst)

    def store(self, inst: IRInstruction, op: IROperand):
        self.update(inst, "store", [op])

    def add_before(self, inst: IRInstruction, opcode: str, args: list[IROperand]) -> IRVariable:
        """
        Insert another instruction before the given instruction
        """
        assert opcode != "phi"
        index = inst.parent.instructions.index(inst)
        var = inst.parent.parent.get_next_variable()
        operands = list(args)
        # TODO: add support for NO_OUTPUT_INSTRUCTIONS
        new_inst = IRInstruction(opcode, operands, output=var)
        inst.parent.insert_instruction(new_inst, index)
        for op in new_inst.operands:
            if isinstance(op, IRVariable):
                self.dfg.add_use(op, new_inst)
        self.dfg.set_producing_instruction(var, new_inst)
        return var
