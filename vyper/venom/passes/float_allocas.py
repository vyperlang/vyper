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
            insts = bb.instructions
            i = 0
            while i < len(insts):
                inst = insts[i]
                if inst.opcode in ("alloca", "palloca", "calloca"):
                    # note: order of allocas impacts bytecode.
                    # TODO: investigate.
                    entry_bb.insert_instruction(inst)

                    # If we move a palloca, also move its immediate param init
                    # store (inserted by ir_node_to_venom). For stack-passed
                    # params, ir_node_to_venom emits mstore immediately after
                    # palloca to copy the param value into memory. We must move
                    # this mstore along with the palloca to ensure the
                    # initialization happens once at function entry, not on
                    # every loop iteration (which would break loop-carried
                    # dependencies).
                    if inst.opcode == "palloca" and i + 1 < len(insts):
                        next_inst = insts[i + 1]
                        if (
                            next_inst.opcode == "mstore"
                            and len(next_inst.operands) >= 2
                            and next_inst.operands[1] == inst.output
                        ):
                            entry_bb.insert_instruction(next_inst)
                            i += 1  # skip the moved init store
                    elif inst.opcode == "palloca":
                        # Debug check: scan for mstore to this palloca later in
                        # the block. If found, the invariant from ir_node_to_venom
                        # (mstore immediately follows palloca) was violated.
                        for j in range(i + 1, len(insts)):
                            later_inst = insts[j]
                            if (
                                later_inst.opcode == "mstore"
                                and len(later_inst.operands) >= 2
                                and later_inst.operands[1] == inst.output
                            ):
                                assert False, (
                                    f"palloca {inst} has init mstore {later_inst} "
                                    f"but not immediately after. This violates the "
                                    f"invariant from ir_node_to_venom and will cause "
                                    f"incorrect loop behavior."
                                )
                else:
                    non_alloca_instructions.append(inst)
                i += 1

            # Replace original instructions with filtered list
            bb.instructions = non_alloca_instructions

        entry_bb.instructions.append(tmp)
