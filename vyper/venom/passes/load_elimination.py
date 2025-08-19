from collections import defaultdict
from typing import Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis, LoadAnalysis
from vyper.venom.basicblock import IRLiteral
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import InstUpdater, IRPass


def _conflict(store_opcode: str, k1: IRLiteral, k2: IRLiteral):
    ptr1, ptr2 = k1.value, k2.value
    # hardcode the size of store opcodes for now. maybe refactor to use
    # vyper.evm.address_space
    if store_opcode == "mstore":
        return abs(ptr1 - ptr2) < 32
    assert store_opcode in ("sstore", "tstore"), "unhandled store opcode"
    return abs(ptr1 - ptr2) < 1


class LoadElimination(IRPass):
    """
    Eliminate sloads, mloads and tloads
    """

    # should this be renamed to EffectsElimination?

    updater: InstUpdater

    def run_pass(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self.load_analysis = self.analyses_cache.request_analysis(LoadAnalysis)

        self._run(Effects.MEMORY, "mload", "mstore")
        self._run(Effects.TRANSIENT, "tload", "tstore")
        self._run(Effects.STORAGE, "sload", "sstore")
        #self._run(None, "dload", None)
        #self._run(None, "calldataload", None)

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _run(self, eff, load_opcode, store_opcode):
        self._lattice = self.load_analysis.lattice[eff]
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == load_opcode:
                    self._handle_load(inst)
                elif inst.opcode == store_opcode:
                    pass

    def equivalent(self, op1, op2):
        return self.dfg.are_equivalent(op1, op2)

    def get_literal(self, op):
        op = self.dfg._traverse_store_chain(op)
        if isinstance(op, IRLiteral):
            return op
        return None

    def _handle_load(self, inst):
        (ptr,) = inst.operands

        existing_value = self._lattice[inst].get(ptr, set())

        assert inst.output is not None  # help mypy

        if len(existing_value) == 1:
            self.updater.store(inst, existing_value.pop())

    def _handle_store(self, inst, store_opcode):
        # mstore [val, ptr]
        val, ptr = inst.operands

        known_ptr: Optional[IRLiteral] = self.get_literal(ptr)
        if known_ptr is None:
            # it's a variable. assign this ptr in the lattice and flush
            # everything else.
            self._lattice = {ptr: val}
            return

        existing_val = self._lattice.get(known_ptr)

        # we found a redundant store, eliminate it
        if self.equivalent(val, existing_val):
            self.updater.nop(inst)
            return

        self._lattice[known_ptr] = val

        # kick out any conflicts
        for existing_key in self._lattice.copy().keys():
            if not isinstance(existing_key, IRLiteral):
                # a variable in the lattice. assign this ptr in the lattice
                # and flush everything else.
                self._lattice = {known_ptr: val}
                break

            if _conflict(store_opcode, known_ptr, existing_key):
                del self._lattice[existing_key]
                self._lattice[known_ptr] = val
