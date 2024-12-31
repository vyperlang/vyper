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
            self._process_bb(bb, Effects.MEMORY, "mload", "mstore")
            self._process_bb(bb, Effects.TRANSIENT, "tload", "tstore")
            self._process_bb(bb, Effects.STORAGE, "sload", "sstore")

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def equivalent(self, op1, op2):
        return op1 == op2 or self.equivalence.equivalent(op1, op2)

    def _process_bb(self, bb, eff, load_opcode, store_opcode):
        # not really a lattice even though it is not really inter-basic block;
        # we may generalize in the future
        lattice = ()

        for inst in bb.instructions:
            if eff in inst.get_write_effects():
                lattice = ()

            if inst.opcode == store_opcode:
                # mstore [val, ptr]
                val, ptr = inst.operands
                lattice = (ptr, val)

            if inst.opcode == load_opcode:
                prev_lattice = lattice
                (ptr,) = inst.operands
                lattice = (ptr, inst.output)
                if not prev_lattice:
                    continue
                if not self.equivalent(ptr, prev_lattice[0]):
                    continue
                inst.opcode = "store"
                inst.operands = [prev_lattice[1]]
