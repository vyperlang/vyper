from vyper.venom.analysis.equivalent_vars import VarEquivalenceAnalysis
from vyper.venom.passes.base_pass import IRPass


class LoadElimination(IRPass):
    """
    Eliminate sloads, mloads and tloads
    """

    def run_pass(self):
        self.equivalence = self.analyses_cache.request_analysis(VarEquivalenceAnalysis)

        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

    def equivalent(self, op1, op2):
        return op1 == op2 or self.equivalence.equivalent(op1, op2)

    def _process_bb(self, bb):
        transient = ()
        storage = ()
        memory = ()

        for inst in bb.instructions:
            if "memory" in inst.get_write_effects():
                memory = ()
            if "storage" in inst.get_write_effects():
                storage = ()
            if "transient" in inst.get_write_effects():
                transient = ()

            if inst.opcode == "mstore":
                # mstore [val, ptr]
                memory = (inst.operands[1], inst.operands[0])
            if inst.opcode == "sstore":
                storage = (inst.operands[1], inst.operands[0])
            if inst.opcode == "tstore":
                transient = (inst.operands[1], inst.operands[0])

            if inst.opcode == "mload":
                prev_memory = memory
                memory = (inst.operands[0], inst.output)
                if not prev_memory:
                    continue
                if not self.equivalent(inst.operands[0], prev_memory[0]):
                    continue
                inst.opcode = "store"
                inst.operands = [prev_memory[1]]

            if inst.opcode == "sload":
                prev_storage = storage
                storage = (inst.operands[0], inst.output)
                if not prev_storage:
                    continue
                if not self.equivalent(inst.operands[0], prev_storage[0]):
                    continue
                inst.opcode = "store"
                inst.operands = [prev_storage[1]]

            if inst.opcode == "tload":
                prev_transient = transient
                transient = (inst.operands[0], inst.output)
                if not prev_transient:
                    continue
                if not self.equivalent(inst.operands[0], prev_transient[0]):
                    continue
                inst.opcode = "store"
                inst.operands = [prev_transient[1]]
