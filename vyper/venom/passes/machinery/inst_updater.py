from typing import Optional

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

    def update(
        self,
        inst: IRInstruction,
        opcode: str,
        new_operands: list[IROperand],
        new_output: Optional[IRVariable] = None,
    ):
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

        if opcode in NO_OUTPUT_INSTRUCTIONS:
            if inst.output is not None:
                assert new_output is None
                #assert len(uses := self.dfg.get_uses(inst.output)) == 0, (inst, uses)
                self.dfg.remove_producing_instruction(inst.output)
                inst.output = None
        else:
            # new_output is None is sentinel meaning "no change"
            if new_output is not None and new_output != inst.output:
                if inst.output is not None:
                    self.dfg.remove_producing_instruction(inst.output)
                self.dfg.set_producing_instruction(new_output, inst)
                inst.output = new_output

        inst.opcode = opcode
        inst.operands = new_operands

    def nop(self, inst: IRInstruction):
        inst.annotation = str(inst)  # copy IRInstruction.make_nop()
        self.update(inst, "nop", [])

    def remove(self, inst: IRInstruction):
        self.nop(inst)  # for dfg updates and checks
        inst.parent.remove_instruction(inst)

    def store(self, inst: IRInstruction, op: IROperand, new_output: Optional[IRVariable] = None):
        self.update(inst, "store", [op], new_output=new_output)

    def add_before(
        self, inst: IRInstruction, opcode: str, args: list[IROperand]
    ) -> Optional[IRVariable]:
        """
        Insert another instruction before the given instruction
        """
        assert opcode != "phi"
        index = inst.parent.instructions.index(inst)

        var = None
        if opcode not in NO_OUTPUT_INSTRUCTIONS:
            var = inst.parent.parent.get_next_variable()

        operands = list(args)
        new_inst = IRInstruction(opcode, operands, output=var)
        inst.parent.insert_instruction(new_inst, index)
        for op in new_inst.operands:
            if isinstance(op, IRVariable):
                self.dfg.add_use(op, new_inst)
        if var is not None:
            self.dfg.set_producing_instruction(var, new_inst)
        return var
