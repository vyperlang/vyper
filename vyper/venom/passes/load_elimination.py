from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis, LoadAnalysis
from vyper.venom.basicblock import IRLiteral, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import InstUpdater, IRPass


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
        self._bb_lattice = self.load_analysis.eff_bb_lattice[eff]
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

        existing_value = self._lattice[inst].get(ptr, OrderedSet()).copy()

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
            # if inst.output is not None and inst.output.name == "%1719":
            # breakpoint()
            for pred in self.cfg.cfg_in(inst.parent):
                pred_lattice = self._bb_lattice[pred]
                if ptr not in pred_lattice:
                    continue
                val = pred_lattice[ptr]
                if len(val) == 0:
                    continue
                if len(val) > 1:
                    # could be handled
                    # but if would require
                    # more phis
                    return
                val = val.first()
                assert val in existing_value
                if not isinstance(val, IRVariable):
                    # tmp fix
                    return
                ops.extend([pred.label, val])

            assert len(ops) == 2 * len(existing_value), (ops, existing_value, inst)

            join = self.updater.add_before(first_inst, "phi", ops)
            assert join is not None
            self.updater.store(inst, join)

    def _handle_store(self, inst):
        # mstore [val, ptr]
        val, ptr = inst.operands

        existing_value = self._lattice[inst].get(ptr, OrderedSet()).copy()

        # we found a redundant store, eliminate it
        if len(existing_value) > 0:
            for tmp in existing_value:
                if not self.equivalent(val, tmp):
                    return
            self.updater.nop(inst)
