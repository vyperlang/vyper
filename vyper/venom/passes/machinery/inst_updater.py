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

        old_outputs = inst.get_outputs()

        if opcode in NO_OUTPUT_INSTRUCTIONS:
            for output in old_outputs:
                assert new_output is None
                assert len(uses := self.dfg.get_uses(output)) == 0, (inst, uses)
                self.dfg.remove_producing_instruction(output)
            inst.set_outputs([])
        else:
            # new_output is None is sentinel meaning "no change"
            if new_output is not None:
                # multi-output instructions are not currently updated this way
                assert len(old_outputs) <= 1

                old_primary = old_outputs[0] if len(old_outputs) > 0 else None

                if old_primary is not None and old_primary != new_output:
                    self.dfg.remove_producing_instruction(old_primary)
                self.dfg.set_producing_instruction(new_output, inst)
                inst.set_outputs([new_output])

        inst.opcode = opcode
        inst.operands = new_operands

        if annotation:
            inst.annotation = original_str + " " + annotation

        return inst

    # similar behaviour as update but it wont change the instruction
    # it self but insert new instruction with new data
    # this is so there is a way to change instruction without
    # changing it inplace if there is such a case where the data
    # would be needed in future such as palloca/calloca pairs
    def replace(
        self,
        inst: IRInstruction,
        opcode: str,
        new_operands: list[IROperand],
        new_output: Optional[IRVariable] = None,
        annotation: str = "",
    ) -> IRInstruction:
        bb = inst.parent
        index = bb.instructions.index(inst)
        new_inst = inst.copy()
        bb.instructions[index] = new_inst
        self.update(new_inst, opcode, new_operands, new_output, annotation)
        assert new_inst.output == inst.output
        self.dfg.set_producing_instruction(new_inst.output, new_inst)
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
            # Check if ANY output has uses
            outputs = inst.get_outputs()
            has_uses = any(len(self.dfg.get_uses(output)) > 0 for output in outputs)
            if has_uses:
                q.append(inst)
            else:
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
        self, inst: IRInstruction, opcode: str, args: list[IROperand], var: IRVariable | None = None
    ) -> Optional[IRVariable]:
        """
        Insert another instruction before the given instruction
        """
        return self._insert_instruction(inst, opcode, args, after=False, var=var)

    def add_after(
        self, inst: IRInstruction, opcode: str, args: list[IROperand], var: IRVariable | None = None
    ) -> Optional[IRVariable]:
        """
        Insert another instruction after the given instruction
        """
        return self._insert_instruction(inst, opcode, args, after=True, var=var)

    def _insert_instruction(
        self, inst: IRInstruction, opcode: str, args: list[IROperand], after: bool = False, var: IRVariable | None = None,
    ) -> Optional[IRVariable]:
        index = inst.parent.instructions.index(inst)
        if after:
            index += 1

        if var is None:
            if opcode not in NO_OUTPUT_INSTRUCTIONS:
                var = inst.parent.parent.get_next_variable()

        operands = list(args)
        new_inst = IRInstruction(opcode, operands, [var] if var is not None else None)
        inst.parent.insert_instruction(new_inst, index)
        for op in new_inst.operands:
            if isinstance(op, IRVariable):
                self.dfg.add_use(op, new_inst)
        if var is not None:
            self.dfg.set_producing_instruction(var, new_inst)
        return var
