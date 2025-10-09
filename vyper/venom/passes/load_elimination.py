from collections import deque

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import InstUpdater, IRPass

Lattice = dict[IROperand, OrderedSet[IROperand]]


def _conflict(store_opcode: str, k1: IRLiteral, k2: IRLiteral):
    ptr1, ptr2 = k1.value, k2.value
    # hardcode the size of store opcodes for now. maybe refactor to use
    # vyper.evm.address_space
    if store_opcode == "mstore":
        return abs(ptr1 - ptr2) < 32
    assert store_opcode in ("sstore", "tstore"), "unhandled store opcode"
    return abs(ptr1 - ptr2) < 1


class LoadAnalysis(IRAnalysis):
    InstToLattice = dict[IRInstruction, Lattice]
    lattice: dict[Effects | str, InstToLattice]
    cfg: CFGAnalysis
    eff_bb_lattice: dict[Effects | str, dict[IRBasicBlock, Lattice]]

    def analyze(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.lattice = dict()
        self.eff_bb_lattice = dict()

        self._analyze_type(Effects.MEMORY, "mload", "mstore")
        self._analyze_type(Effects.TRANSIENT, "tload", "tstore")
        self._analyze_type(Effects.STORAGE, "sload", "sstore")
        self._analyze_type("dload", "dload", None)
        self._analyze_type("calldataload", "calldataload", None)

    def _analyze_type(self, eff: Effects | str, load_opcode: str, store_opcode: str | None):
        self.inst_to_lattice: LoadAnalysis.InstToLattice = dict()
        self.bb_to_lattice: dict[IRBasicBlock, Lattice] = dict()

        worklist = deque(self.cfg.dfs_pre_walk)

        while len(worklist) > 0:
            bb = worklist.popleft()
            change = self._handle_bb(eff, load_opcode, store_opcode, bb)

            if change:
                for succ in self.cfg.cfg_out(bb):
                    worklist.append(succ)

        self.lattice[eff] = self.inst_to_lattice
        self.eff_bb_lattice[eff] = self.bb_to_lattice

    def _merge(self, bb: IRBasicBlock) -> Lattice:
        preds = list(self.cfg.cfg_in(bb))
        if len(preds) == 0:
            return dict()
        res = self.bb_to_lattice.get(preds[0], dict()).copy()

        for pred in preds[1:]:
            other = self.bb_to_lattice.get(pred, dict())
            common_keys = other.keys() & res.keys()
            tmp = res.copy()
            res = dict()
            for key in common_keys:
                res[key] = tmp[key] | other[key]

        return res

    def get_literal(self, op):
        op = self.dfg._traverse_assign_chain(op)
        if isinstance(op, IRLiteral):
            return op
        return None

    def _handle_bb(
        self, eff: Effects | str, load_opcode: str, store_opcode: str | None, bb: IRBasicBlock
    ):
        lattice = self._merge(bb)

        for inst in bb.instructions:
            if inst.opcode == load_opcode:
                self.inst_to_lattice[inst] = lattice.copy()
                ptr = inst.operands[0]
                assert inst.output is not None
                lattice[ptr] = OrderedSet([inst.output])
            elif inst.opcode == store_opcode:
                self.inst_to_lattice[inst] = lattice.copy()
                # mstore [val, ptr]
                val, ptr = inst.operands
                lit = self.get_literal(ptr)
                if lit is None:
                    lattice.clear()
                    lattice[ptr] = OrderedSet([val])
                    continue

                assert lit is not None

                # kick out any conflicts
                for existing_key in lattice.copy().keys():
                    existing_lit = self.get_literal(existing_key)
                    if existing_lit is None:
                        # a variable in the lattice. assign this ptr in the lattice
                        # and flush everything else.
                        lattice.clear()
                        lattice[ptr] = OrderedSet([val])
                        break

                    if store_opcode is not None:
                        if _conflict(store_opcode, lit, existing_lit):
                            del lattice[existing_key]

                lattice[ptr] = OrderedSet([val])
            elif isinstance(eff, Effects) and eff in inst.get_write_effects():
                lattice.clear()

        if bb not in self.bb_to_lattice or self.bb_to_lattice[bb] != lattice:
            self.bb_to_lattice[bb] = lattice.copy()
            return True
        return False


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

    def _handle_load(self, inst):
        (ptr,) = inst.operands

        existing_value = self._lattice[inst].get(ptr, OrderedSet()).copy()

        assert inst.output is not None  # help mypy

        if len(existing_value) == 1:
            self.updater.mk_assign(inst, existing_value.pop())
        elif len(existing_value) > 1:
            bb = inst.parent
            while len(preds := self.cfg.cfg_in(bb)) == 1:
                bb = preds.first()
            first_inst = bb.instructions[0]
            ops = []
            for pred in self.cfg.cfg_in(bb):
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
                    # could be extended by
                    # adding stores to source
                    # basicblocks
                    return
                ops.extend([pred.label, val])

            assert len(ops) == 2 * len(existing_value), (ops, existing_value, inst)

            join = self.updater.add_before(first_inst, "phi", ops)
            assert join is not None
            self.updater.mk_assign(inst, join)

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
