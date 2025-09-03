from collections import deque
from typing import Iterable, Optional

from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import DFGAnalysis
from vyper.venom.basicblock import NO_OUTPUT_INSTRUCTIONS, IRInstruction, IROperand, IRVariable


class InstUpdater:
    """
    A helper class for updating instructions which also updates the
    basic block and dfg in place
    """

    def __init__(self, dfg: DFGAnalysis):
        self.dfg = dfg

    def update_operands(
        self, inst: IRInstruction, replace_dict: dict[IROperand, IROperand], annotation: str = ""
    ):
        old_operands = inst.operands
        new_operands = [replace_dict[op] if op in replace_dict else op for op in old_operands]
        self.update(inst, inst.opcode, new_operands, annotation=annotation)

    # move the uses of old_var to new_inst
    def move_uses(self, old_var: IRVariable, new_inst: IRInstruction):
        assert new_inst.output is not None
        new_var = new_inst.output

        for use in list(self.dfg.get_uses(old_var)):
            self.update_operands(use, {old_var: new_var})

    def update(
        self,
        inst: IRInstruction,
        opcode: str,
        new_operands: list[IROperand],
        new_output: Optional[IRVariable] = None,
        annotation: str = "",
    ) -> IRInstruction:
        # sanity
        assert all(isinstance(op, IROperand) for op in new_operands)

        original_str = str(inst)

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
                assert len(uses := self.dfg.get_uses(inst.output)) == 0, (inst, uses)
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

        if annotation:
            inst.annotation = original_str + " " + annotation

        return inst

    def nop(self, inst: IRInstruction, annotation: str = ""):
        self.update(inst, "nop", [], annotation=annotation)

    def nop_multi(self, to_nop: Iterable[IRInstruction]):
        q = deque(to_nop)

        bound = (2 + len(q)) ** 2  # set bound to at least 2**2
        for _ in range(bound):  # bounded `while True`
            if len(q) == 0:
                return
            # NOTE: this doesn't work for dfg cycles.
            inst = q.popleft()
            if inst.output and len(self.dfg.get_uses(inst.output)) > 0:
                q.append(inst)
                continue
            self.nop(inst)

        # this should only happen if we try to delete a dfg cycle, cross
        # that bridge when we get to it.
        raise CompilerPanic("infinite loop")  # pragma: nocover

    def remove(self, inst: IRInstruction):
        self.nop(inst)  # for dfg updates and checks
        inst.parent.remove_instruction(inst)

    def mk_assign(
        self, inst: IRInstruction, op: IROperand, new_output: Optional[IRVariable] = None
    ):
        self.update(inst, "assign", [op], new_output=new_output)

    def add_before(
        self, inst: IRInstruction, opcode: str, args: list[IROperand]
    ) -> Optional[IRVariable]:
        """
        Insert another instruction before the given instruction
        """
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
