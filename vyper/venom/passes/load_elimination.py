from collections import defaultdict
from typing import Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis, LoadAnalysis, DominatorTreeAnalysis
from vyper.venom.basicblock import IRLiteral, IRVariable
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
        self._run("dload", "dload", None)
        self._run("calldataload", "calldataload", None)

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _run(self, eff, load_opcode, store_opcode):
        self._lattice = self.load_analysis.lattice[eff]
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions.copy():
                if inst.opcode == load_opcode:
                    self._handle_load(inst)
                elif inst.opcode == store_opcode:
                    self._handle_store(inst)

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
        elif len(existing_value) > 1:
            bb = inst.parent
            while len(preds := self.cfg.cfg_in(bb)) == 1:
                assert len(preds) != 0
                bb = preds.first()
            first_inst = bb.instructions[0]
            ops = []
            for val in existing_value:
                if not isinstance(val, IRVariable):
                    return
                src = self.dfg.get_producing_instruction(val)
                assert src is not None
                ops.extend([src.parent.label, val])


            join = self.updater.add_before(first_inst, "phi", ops)
            assert join is not None
            self.updater.store(inst, join)


    def _handle_store(self, inst):
        # mstore [val, ptr]
        val, ptr = inst.operands

        existing_value = self._lattice[inst].get(ptr, set())

        # we found a redundant store, eliminate it
        if len(existing_value) == 1:
            if self.equivalent(val, existing_value.pop()):
                self.updater.nop(inst)
                return
