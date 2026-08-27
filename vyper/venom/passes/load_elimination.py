from vyper.utils import OrderedSet
from vyper.venom.analysis import (
    BasePtrAnalysis,
    CFGAnalysis,
    DFGAnalysis,
    LivenessAnalysis,
    LoadAnalysis,
)
from vyper.venom.basicblock import IRVariable
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
        self.load_analysis = self.analyses_cache.force_analysis(LoadAnalysis)

        self._run(Effects.MEMORY, "mload", "mstore")
        self._run(Effects.TRANSIENT, "tload", "tstore")
        self._run(Effects.STORAGE, "sload", "sstore")
        self._run("dload", "dload", None)
        self._run("calldataload", "calldataload", None)

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()

        self.analyses_cache.invalidate_analysis(LoadAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)

    def _run(self, eff, load_opcode, store_opcode):
        self._lattice = self.load_analysis.lattice[eff]
        self._bb_lattice = self.load_analysis.eff_bb_lattice[eff]
        self.space = self.load_analysis.get_space(eff)
        self.load_analysis.space = self.space
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions.copy():
                if inst.opcode == load_opcode:
                    self._handle_load(inst)
                elif inst.opcode == store_opcode:
                    self._handle_store(inst)

    def equivalent(self, op1, op2):
        return self.dfg.are_equivalent(op1, op2)

    def _handle_load(self, inst):
        ptr = self.load_analysis.get_read(inst)

        existing_value = self._lattice[inst].get(ptr, OrderedSet()).copy()

        if len(existing_value) == 1:
            self.updater.mk_assign(inst, existing_value.pop())
        elif len(existing_value) > 1:
            bb = inst.parent
            while len(preds := self.cfg.cfg_in(bb)) == 1:
                bb = preds.first()
            first_inst = bb.instructions[0]
            preds = list(self.cfg.cfg_in(bb))
            ops = []
            for pred in preds:
                pred_lattice = self._bb_lattice[pred]
                # KeyError here indicates analysis bug (ptr must be in all preds)
                val = pred_lattice[ptr]
                assert len(val) > 0, (ptr, pred, val)
                if len(val) > 1:
                    # could be handled but would require more phis
                    return
                val = val.first()
                assert val in existing_value, (val, existing_value)
                if not isinstance(val, IRVariable):
                    # could be extended by adding stores to source basicblocks
                    return
                ops.extend([pred.label, val])

            # each predecessor contributes exactly one (label, value) pair;
            # note: len(preds) != len(existing_value) when multiple preds have same value
            assert len(ops) == 2 * len(preds), (ops, preds, inst)

            join = self.updater.add_before(first_inst, "phi", ops)
            assert join is not None
            self.updater.mk_assign(inst, join)

    def _handle_store(self, inst):
        # mstore [val, ptr]
        val, _ = inst.operands
        ptr = self.load_analysis.get_write(inst)

        existing_value = self._lattice[inst].get(ptr, OrderedSet()).copy()

        # we found a redundant store, eliminate it
        if len(existing_value) > 0:
            for tmp in existing_value:
                if not self.equivalent(val, tmp):
                    return
            self.updater.nop(inst)
