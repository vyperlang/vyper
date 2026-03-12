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

            if inst.opcode != "alloca":
                non_alloca.append(inst)
                i += 1
                continue

            # note: order of allocas impacts bytecode.
            # TODO: investigate.
            entry_bb.insert_instruction(inst)

            i += 1

        return non_alloca
