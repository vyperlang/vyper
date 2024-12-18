from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis, VarEquivalenceAnalysis
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import IRPass


class LoadElimination(IRPass):
    """
    Eliminate sloads, mloads and tloads
    """

    # should this be renamed to EffectsElimination?

    def run_pass(self):
        self.equivalence = self.analyses_cache.request_analysis(VarEquivalenceAnalysis)

        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def equivalent(self, op1, op2):
        return op1 == op2 or self.equivalence.equivalent(op1, op2)

    def _process_bb(self, bb):
        transient = ()
        storage = ()
        memory = ()

        for inst in bb.instructions:
            if Effects.MEMORY in inst.get_write_effects():
                memory = ()
            if Effects.STORAGE in inst.get_write_effects():
                storage = ()
            if Effects.TRANSIENT in inst.get_write_effects():
                transient = ()

            if inst.opcode == "mstore":
                # mstore [val, ptr]
                val, ptr = inst.operands
                memory = (ptr, val)
            if inst.opcode == "sstore":
                val, ptr = inst.operands
                storage = (ptr, val)
            if inst.opcode == "tstore":
                val, ptr = inst.operands
                transient = (ptr, val)

            if inst.opcode == "mload":
                prev_memory = memory
                ptr, = inst.operands
                memory = (ptr, inst.output)
                if not prev_memory:
                    continue
                if not self.equivalent(ptr, prev_memory[0]):
                    continue
                inst.opcode = "store"
                inst.operands = [prev_memory[1]]

            if inst.opcode == "sload":
                prev_storage = storage
                ptr, = inst.operands
                storage = (ptr, inst.output)
                if not prev_storage:
                    continue
                if not self.equivalent(ptr, prev_storage[0]):
                    continue
                inst.opcode = "store"
                inst.operands = [prev_storage[1]]

            if inst.opcode == "tload":
                prev_transient = transient
                ptr, = inst.operands
                transient = (ptr, inst.output)
                if not prev_transient:
                    continue
                if not self.equivalent(ptr, prev_transient[0]):
                    continue
                inst.opcode = "store"
                inst.operands = [prev_transient[1]]
