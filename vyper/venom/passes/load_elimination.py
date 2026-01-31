from collections import deque

import vyper.evm.address_space as addr_space
from vyper.evm.address_space import CALLDATA, DATA, AddrSpace
from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis import BasePtrAnalysis, CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis.mem_alias import mem_alias_type_factory
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.effects import Effects, to_addr_space
from vyper.venom.memory_location import InstAccessOps, MemoryLocation
from vyper.venom.passes.base_pass import InstUpdater, IRPass

# from position in the memory to the posible values
Lattice = dict[IROperand | MemoryLocation, OrderedSet[IROperand]]


class LoadAnalysis(IRAnalysis):
    InstToLattice = dict[IRInstruction, Lattice]
    lattice: dict[Effects | str, InstToLattice]
    cfg: CFGAnalysis
    eff_bb_lattice: dict[Effects | str, dict[IRBasicBlock, Lattice]]

    def analyze(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.lattice = dict()
        self.eff_bb_lattice = dict()

        self._analyze_type(Effects.MEMORY, "mload", "mstore")
        self._analyze_type(Effects.TRANSIENT, "tload", "tstore")
        self._analyze_type(Effects.STORAGE, "sload", "sstore")
        self._analyze_type("dload", "dload", None)
        self._analyze_type("calldataload", "calldataload", None)

    def get_space(self, eff: Effects | str) -> AddrSpace:
        if isinstance(eff, Effects):
            ret = to_addr_space(eff)
            assert ret is not None
            return ret
        if eff == "dload":
            return DATA
        if eff == "calldataload":
            return CALLDATA

        raise CompilerPanic(f"invalid effect {eff}")  # pragma: nocover

    @property
    def word_scale(self) -> int:
        return self.space.word_scale

    def _analyze_type(self, eff: Effects | str, load_opcode: str, store_opcode: str | None):
        self.space = self.get_space(eff)

        if store_opcode is not None:
            mem_alias_type = mem_alias_type_factory(self.space)
            self.mem_alias = self.analyses_cache.request_analysis(mem_alias_type)
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

    def get_memloc(self, op: IROperand | MemoryLocation) -> MemoryLocation:
        if isinstance(op, MemoryLocation):
            return op
        if isinstance(op, IRVariable):
            op = self.dfg._traverse_assign_chain(op)
        assert isinstance(op, (IRVariable, IRLiteral))
        access_ops = InstAccessOps(ofst=op, size=IRLiteral(self.word_scale))
        return self.base_ptrs.segment_from_ops(access_ops)

    def _normalize_operand(self, op: IROperand) -> IROperand:
        """Normalize operand through assign chain for consistent lattice keys."""
        if isinstance(op, IRVariable):
            return self.dfg._traverse_assign_chain(op)
        return op

    def get_read(self, inst: IRInstruction) -> IROperand | MemoryLocation:
        assert inst.opcode == self.space.load_op  # sanity
        if self.space in (
            addr_space.MEMORY,
            addr_space.TRANSIENT,
            addr_space.STORAGE,
            addr_space.CALLDATA,
        ):
            memloc = self.base_ptrs.get_read_location(inst, self.space)
            if memloc.is_fixed:
                return memloc
        return self._normalize_operand(inst.operands[0])

    def get_write(self, inst: IRInstruction) -> IROperand | MemoryLocation:
        assert inst.opcode == self.space.store_op  # sanity
        if self.space in (addr_space.MEMORY, addr_space.TRANSIENT, addr_space.STORAGE):
            memloc = self.base_ptrs.get_write_location(inst, self.space)
            if memloc.is_fixed:
                return memloc
        return self._normalize_operand(inst.operands[1])

    def _handle_bb(
        self, eff: Effects | str, load_opcode: str, store_opcode: str | None, bb: IRBasicBlock
    ):
        lattice = self._merge(bb)

        for inst in bb.instructions:
            if inst.opcode == load_opcode:
                self.inst_to_lattice[inst] = lattice.copy()
                ptr = self.get_read(inst)
                lattice[ptr] = OrderedSet([inst.output])
            elif inst.opcode == store_opcode:
                self.inst_to_lattice[inst] = lattice.copy()
                # mstore [val, ptr]
                val, _ = inst.operands
                ptr = self.get_write(inst)
                memloc = self.get_memloc(ptr)

                # kick out any conflicts
                for existing_key in lattice.copy().keys():
                    existing_loc = self.get_memloc(existing_key)
                    if self.mem_alias.may_alias(existing_loc, memloc):
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
        self.load_analysis = self.analyses_cache.force_analysis(LoadAnalysis)

        self._run(Effects.MEMORY, "mload", "mstore")
        self._run(Effects.TRANSIENT, "tload", "tstore")
        self._run(Effects.STORAGE, "sload", "sstore")
        self._run("dload", "dload", None)
        self._run("calldataload", "calldataload", None)

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()

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
