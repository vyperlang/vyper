from vyper.venom.basicblock import IRInstruction, IRLiteral
from vyper.venom.passes.base_pass import IRPass


class FloatAllocas(IRPass):
    """
    This pass moves allocas to the entry basic block of a function
    We could probably move them to the immediate dominator of the basic
    block defining the alloca instead of the entry (which dominates all
    basic blocks), but this is done for expedience.
    Without this step, sccp fails, possibly because dominators are not
    guaranteed to be traversed first.
    """

    def run_pass(self):
        entry_bb = self.function.entry
        assert entry_bb.is_terminated, entry_bb
        tmp = entry_bb.instructions.pop()

        for bb in self.function.get_basic_blocks():
            if bb is entry_bb:
                continue

            bb.instructions = self._float_allocas_from_block(bb, entry_bb)

        entry_bb.instructions.append(tmp)

    def _float_allocas_from_block(self, bb, entry_bb):
        insts = bb.instructions
        non_alloca = []
        i = 0

        while i < len(insts):
            inst = insts[i]

            if inst.opcode not in ("alloca", "palloca", "calloca"):
                non_alloca.append(inst)
                i += 1
                continue

            # note: order of allocas impacts bytecode.
            # TODO: investigate.
            entry_bb.insert_instruction(inst)

            if inst.opcode == "palloca" and self._move_palloca_init_store(entry_bb, insts, i, inst):
                i += 2  # skip the moved init store
                continue

            i += 1

        return non_alloca

    def _move_palloca_init_store(
        self, entry_bb, insts: list[IRInstruction], idx: int, palloca_inst: IRInstruction
    ) -> bool:
        """
        Move the synthetic palloca init store (stack-passed params only) to entry.
        Returns True if an init store was moved and should be skipped in the caller.
        """
        if idx + 1 >= len(insts):
            return False

        next_inst = insts[idx + 1]
        if not self._is_palloca_init_store(palloca_inst, next_inst):
            return False

        entry_bb.insert_instruction(next_inst)
        return True

    def _is_palloca_init_store(
        self, palloca_inst: IRInstruction, mstore_inst: IRInstruction
    ) -> bool:
        if mstore_inst.opcode != "mstore" or len(mstore_inst.operands) < 2:
            return False

        if mstore_inst.operands[1] != palloca_inst.output:
            return False

        alloca_id = palloca_inst.operands[1]
        if not isinstance(alloca_id, IRLiteral):
            return False

        param = self.function.get_param_by_id(alloca_id.value)
        if param is None:
            return False

        return mstore_inst.operands[0] == param.func_var
