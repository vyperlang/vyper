from collections import deque
from typing import Callable, Optional

import vyper.evm.address_space as addr_space
from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.effects import Effects, to_addr_space
from vyper.venom.memory_location import InstAccessOps, MemoryLocation

from .analysis import IRAnalysis
from .base_ptr_analysis import BasePtrAnalysis
from .cfg import CFGAnalysis
from .dfg import DFGAnalysis
from .mem_alias import (
    MemoryAliasAnalysis,
    StorageAliasAnalysis,
    TransientAliasAnalysis,
    mem_alias_type_factory,
)

_LatticeKey = IROperand | MemoryLocation
_GetMemloc = Callable[[_LatticeKey], MemoryLocation]


class Lattice:
    """
    Maps memory positions to possible values, with an optional reverse
    index from MemoryLocation to lattice keys for fast alias invalidation.
    """

    def __init__(self, get_memloc: Optional[_GetMemloc] = None):
        self._entries: dict[_LatticeKey, OrderedSet[IROperand]] = {}
        self._by_memloc: dict[MemoryLocation, set[_LatticeKey]] = {}
        self._get_memloc = get_memloc

    def _track_memloc(self, key: _LatticeKey):
        if self._get_memloc is not None:
            loc = self._get_memloc(key)
            if loc not in self._by_memloc:
                self._by_memloc[loc] = set()
            self._by_memloc[loc].add(key)

    def __setitem__(self, key: _LatticeKey, value: OrderedSet[IROperand]):
        self._entries[key] = value
        self._track_memloc(key)

    def __getitem__(self, key: _LatticeKey) -> OrderedSet[IROperand]:
        return self._entries[key]

    def __contains__(self, key: _LatticeKey) -> bool:
        return key in self._entries

    def __iter__(self):
        return iter(self._entries)

    def __len__(self):
        return len(self._entries)

    def __eq__(self, other):
        if isinstance(other, Lattice):
            return self._entries == other._entries
        return NotImplemented

    def keys(self):
        return self._entries.keys()

    def get(self, key, default=None):
        return self._entries.get(key, default)

    def copy(self) -> "Lattice":
        new = Lattice(self._get_memloc)
        new._entries = self._entries.copy()
        new._by_memloc = {k: v.copy() for k, v in self._by_memloc.items()}
        return new

    def clear(self):
        self._entries.clear()
        self._by_memloc.clear()

    def _remove_memloc(self, loc: MemoryLocation):
        keys = self._by_memloc.pop(loc, None)
        if keys is not None:
            for key in keys:
                self._entries.pop(key, None)

    def remove_aliases(self, memloc: MemoryLocation, alias_set):
        """Remove all lattice entries for memloc and its aliases."""
        self._remove_memloc(memloc)
        for loc in alias_set:
            self._remove_memloc(loc)


class LoadAnalysis(IRAnalysis):
    InstToLattice = dict[IRInstruction, Lattice]
    lattice: dict[Effects | str, InstToLattice]
    cfg: CFGAnalysis
    eff_bb_lattice: dict[Effects | str, dict[IRBasicBlock, Lattice]]

    def analyze(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.lattice = {}
        self.eff_bb_lattice = {}

        self._analyze_type(Effects.MEMORY, "mload", "mstore")
        self._analyze_type(Effects.TRANSIENT, "tload", "tstore")
        self._analyze_type(Effects.STORAGE, "sload", "sstore")
        self._analyze_type("dload", "dload", None)
        self._analyze_type("calldataload", "calldataload", None)

    def invalidate(self):
        self.analyses_cache.invalidate_analysis(MemoryAliasAnalysis)
        self.analyses_cache.invalidate_analysis(StorageAliasAnalysis)
        self.analyses_cache.invalidate_analysis(TransientAliasAnalysis)

    def get_space(self, eff: Effects | str) -> addr_space.AddrSpace:
        if isinstance(eff, Effects):
            ret = to_addr_space(eff)
            assert ret is not None
            return ret
        if eff == "dload":
            return addr_space.DATA
        if eff == "calldataload":
            return addr_space.CALLDATA

        raise CompilerPanic(f"invalid effect {eff}")  # pragma: nocover

    @property
    def word_scale(self) -> int:
        return self.space.word_scale

    def _analyze_type(self, eff: Effects | str, load_opcode: str, store_opcode: str | None):
        self.space = self.get_space(eff)

        if store_opcode is not None:
            mem_alias_type = mem_alias_type_factory(self.space)
            self.mem_alias = self.analyses_cache.request_analysis(mem_alias_type)
            self._memloc_fn: Optional[_GetMemloc] = self._get_memloc_with_ensure
        else:
            self._memloc_fn = None

        self.inst_to_lattice: LoadAnalysis.InstToLattice = {}
        self.bb_to_lattice: dict[IRBasicBlock, Lattice] = {}

        worklist = deque(self.cfg.dfs_pre_walk)

        while len(worklist) > 0:
            bb = worklist.popleft()
            change = self._handle_bb(eff, load_opcode, store_opcode, bb)

            if change:
                for succ in self.cfg.cfg_out(bb):
                    worklist.append(succ)

        self.lattice[eff] = self.inst_to_lattice
        self.eff_bb_lattice[eff] = self.bb_to_lattice

    def _make_lattice(self) -> Lattice:
        return Lattice(self._memloc_fn)

    def _merge(self, bb: IRBasicBlock) -> Lattice:
        preds = list(self.cfg.cfg_in(bb))
        if len(preds) == 0:
            return self._make_lattice()

        first = self.bb_to_lattice.get(preds[0])
        res = first.copy() if first is not None else self._make_lattice()

        for pred in preds[1:]:
            other = self.bb_to_lattice.get(pred)
            if other is None:
                return self._make_lattice()
            common_keys = other.keys() & res.keys()
            tmp = res
            res = self._make_lattice()
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

    def _get_memloc_with_ensure(self, op: IROperand | MemoryLocation) -> MemoryLocation:
        loc = self.get_memloc(op)
        self.mem_alias.ensure_analyzed(loc)
        return loc

    def _normalize_operand(self, op: IROperand) -> IROperand:
        if isinstance(op, IRVariable):
            return self.dfg._traverse_assign_chain(op)
        return op

    def get_read(self, inst: IRInstruction) -> IROperand | MemoryLocation:
        assert inst.opcode == self.space.load_op
        if self.space != addr_space.DATA:
            memloc = self.base_ptrs.get_read_location(inst, self.space)
            if memloc.is_fixed:
                return memloc
        return self._normalize_operand(inst.operands[0])

    def get_write(self, inst: IRInstruction) -> IROperand | MemoryLocation:
        assert inst.opcode == self.space.store_op
        if self.space in (addr_space.MEMORY, addr_space.TRANSIENT, addr_space.STORAGE):
            memloc = self.base_ptrs.get_write_location(inst, self.space)
            if memloc.is_fixed:
                return memloc
        return self._normalize_operand(inst.operands[1])

    def _handle_bb(
        self, eff: Effects | str, load_opcode: str, store_opcode: str | None, bb: IRBasicBlock
    ) -> bool:
        lattice = self._merge(bb)

        for inst in bb.instructions:
            if inst.opcode == load_opcode:
                self.inst_to_lattice[inst] = lattice.copy()
                ptr = self.get_read(inst)
                lattice[ptr] = OrderedSet([inst.output])
            elif inst.opcode == store_opcode:
                self.inst_to_lattice[inst] = lattice.copy()
                val, _ = inst.operands
                ptr = self.get_write(inst)
                memloc = self.get_memloc(ptr)
                self.mem_alias.ensure_analyzed(memloc)
                alias_set = self.mem_alias.get_alias_set(memloc)
                assert alias_set is not None
                lattice.remove_aliases(memloc, alias_set)
                lattice[ptr] = OrderedSet([val])
            elif isinstance(eff, Effects) and eff in inst.get_write_effects():
                lattice.clear()

        if bb not in self.bb_to_lattice or self.bb_to_lattice[bb] != lattice:
            self.bb_to_lattice[bb] = lattice
            return True
        return False
