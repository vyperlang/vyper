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

            # Extract alloca instructions
            non_alloca_instructions = []
            for inst in bb.instructions:
                if inst.opcode in ("alloca", "palloca", "calloca"):
                    # note: order of allocas impacts bytecode.
                    # TODO: investigate.
                    entry_bb.insert_instruction(inst)
                else:
                    non_alloca_instructions.append(inst)

            # Replace original instructions with filtered list
            bb.instructions = non_alloca_instructions

        entry_bb.instructions.append(tmp)
