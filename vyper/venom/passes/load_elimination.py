from typing import Optional

from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRLiteral
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import IRPass


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

    def run_pass(self):
        for bb in self.function.get_basic_blocks():
            self._process_bb(bb, Effects.MEMORY, "mload", "mstore")
            self._process_bb(bb, Effects.TRANSIENT, "tload", "tstore")
            self._process_bb(bb, Effects.STORAGE, "sload", "sstore")
            self._process_bb(bb, None, "dload", None)
            self._process_bb(bb, None, "calldataload", None)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def equivalent(self, op1, op2):
        return op1 == op2

    def get_literal(self, op):
        if isinstance(op, IRLiteral):
            return op
        return None

    def _process_bb(self, bb, eff, load_opcode, store_opcode):
        # not really a lattice even though it is not really inter-basic block;
        # we may generalize in the future
        self._lattice = {}

        for inst in bb.instructions:
            if inst.opcode == store_opcode:
                self._handle_store(inst, store_opcode)

            elif eff is not None and eff in inst.get_write_effects():
                self._lattice = {}

            elif inst.opcode == load_opcode:
                self._handle_load(inst)

    def _handle_load(self, inst):
        (ptr,) = inst.operands

        existing_value = self._lattice.get(ptr)

        assert inst.output is not None  # help mypy

        # "cache" the value for future load instructions
        self._lattice[ptr] = inst.output

        if existing_value is not None:
            inst.opcode = "store"
            inst.operands = [existing_value]

    def _handle_store(self, inst, store_opcode):
        # mstore [val, ptr]
        val, ptr = inst.operands

        known_ptr: Optional[IRLiteral] = self.get_literal(ptr)
        if known_ptr is None:
            # it's a variable. assign this ptr in the lattice and flush
            # everything else.
            self._lattice = {ptr: val}
            return

        # we found a redundant store, eliminate it
        existing_val = self._lattice.get(known_ptr)
        if self.equivalent(val, existing_val):
            inst.make_nop()
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
