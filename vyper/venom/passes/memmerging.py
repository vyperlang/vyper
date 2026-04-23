from bisect import bisect_left
from dataclasses import dataclass

from vyper.evm.address_space import AddrSpace, CALLDATA, MEMORY, DATA
from vyper.evm.opcodes import version_check
from vyper.utils import OrderedSet
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis, BasePtrAnalysis, MemoryAliasAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import InstUpdater, IRPass
from vyper.venom.memory_location import Allocation, MemoryLocation


@dataclass
class _Copy:
    # abstract "copy" operation which contains a list of copy instructions
    # and can fuse them into a single copy operation.
    dst_loc: MemoryLocation
    src_loc: MemoryLocation
    insts: list[IRInstruction]

    @classmethod
    def memzero(cls, dst: MemoryLocation, insts):
        # factory method to simplify creation of memory zeroing operations
        # (which are similar to Copy operations but src is always
        # `calldatasize`). choose src=dst, so that can_merge returns True
        # for overlapping memzeros.
        return cls(dst, dst, insts)

    @property
    def src(self) -> int:
        assert self.src_loc.offset is not None
        return self.src_loc.offset
    
    @property
    def dst(self) -> int:
        assert self.dst_loc.offset is not None
        return self.dst_loc.offset

    @property
    def src_end(self) -> int:
        assert self.src_loc.offset is not None
        return self.src_loc.offset + self.length
    
    @property
    def length(self) -> int:
        assert self.is_valid
        assert self.src_loc.size is not None
        assert self.src_loc.size == self.dst_loc.size
        return self.src_loc.size

    @property
    def dst_end(self) -> int:
        assert self.dst_loc.offset is not None
        return self.dst_loc.offset + self.length

    def overwrites_self_src(self) -> bool:
        # return true if dst overlaps src. this is important for blocking
        # mcopy batching in certain cases.
        return self.overwrites(self.src_loc)

    def overwrites(self, interval: MemoryLocation) -> bool:
        # return true if dst of self overwrites the interval
        return MemoryLocation.may_overlap(self.dst_loc, interval)
    
    def is_compatible(self, other: "_Copy") -> bool:
        assert self.is_valid
        assert other.is_valid

        return self.src_loc.alloca == other.src_loc.alloca and self.dst_loc.alloca == other.dst_loc.alloca

    def is_valid(self) -> bool:
        return self.dst_loc.is_fixed and self.src_loc.is_fixed

    def can_merge(self, other: "_Copy"):
        assert self.is_compatible(other)

        # both source and destination have to be offset by same amount,
        # otherwise they do not represent the same copy. e.g.
        # Copy(0, 64, 16)
        # Copy(11, 74, 16)
        if self.src - other.src != self.dst - other.dst:
            return False

        # the copies must at least touch each other
        if other.dst > self.dst_end:
            return False

        return True

    def merge(self, other: "_Copy"):
        # merge other into self. e.g.
        # Copy(0, 64, 16); Copy(16, 80, 8) => Copy(0, 64, 24)

        assert self.dst <= other.dst, "bad bisect_left"
        assert self.can_merge(other)

        new_length = max(self.dst_end, other.dst_end) - self.dst
        self.src_loc = MemoryLocation(self.src, new_length, self.src_loc.alloca, self.src_loc._is_volatile)
        self.dst_loc = MemoryLocation(self.dst, new_length, self.dst_loc.alloca, self.dst_loc._is_volatile)
        self.insts.extend(other.insts)

    def __repr__(self) -> str:
        return f"_Copy({self.dst_loc}, {self.src_loc}, {self.length})"


class _Copies:
    # src allocations -> dst allocations -> list
    copies: dict[Allocation | None, dict[Allocation | None, list[_Copy]]]
    just_abstract: bool

    def __init__(self, just_abstract: bool):
        self.copies = dict()
        self.just_abstract = just_abstract
    
    def _check_state(self, source: Allocation | None) -> bool:
        if self.just_abstract:
            is_abstract = source is not None
            return self.just_abstract == is_abstract
        return True

    def get_compatible(self, copy: _Copy) -> list[_Copy]:
        return self.get_copies(copy.src_loc.alloca, copy.dst_loc.alloca)

    def get_copies(self, src_allocation: Allocation | None, dst_allocation: Allocation | None) -> list[_Copy]: 
        assert not self.just_abstract or (src_allocation is None) == (dst_allocation is None), (src_allocation, dst_allocation)
        assert self._check_state(src_allocation)

        if src_allocation not in self.copies:
            self.copies[src_allocation] = dict()
        if dst_allocation not in self.copies[src_allocation]:
            self.copies[src_allocation][dst_allocation] = []
        return self.copies[src_allocation][dst_allocation]

    def insert(self, new_copy: _Copy):
        copies = self.get_compatible(new_copy)
        index = bisect_left(copies, new_copy.dst, key=lambda c: c.dst)
        
        if new_copy.src_loc.alloca not in self.copies:
            self.copies[new_copy.src_loc.alloca] = dict()
        if new_copy.dst_loc.alloca not in self.copies[new_copy.src_loc.alloca]:
            self.copies[new_copy.src_loc.alloca][new_copy.dst_loc.alloca] = []

        copies = self.copies[new_copy.src_loc.alloca][new_copy.dst_loc.alloca]
        copies.insert(index, new_copy)

        i = max(index - 1, 0)
        while i < min(index + 1, len(copies) - 1):
            if copies[i].can_merge(copies[i + 1]):
                copies[i].merge(copies[i + 1])
                del copies[i + 1]
            else:
                i += 1

    def remove(self, copy: _Copy):
        assert self.just_abstract == (not copy.src_loc.is_concrete)
        
        self.copies[copy.src_loc.alloca][copy.dst_loc.alloca].remove(copy)

    def get_reads_from(self, src_allocation: Allocation | None):
        assert self._check_state(src_allocation)

        if src_allocation in self.copies:
            for copies in self.copies[src_allocation].values():
                for copy in copies:
                    yield copy

    def get_writes_to(self, dst_allocation: Allocation | None):
        for srcs in self.copies.values():
            if dst_allocation not in srcs:
                continue
            for copy in srcs[dst_allocation]:
                yield copy

    def get_all_lists(self):
        for srcs in self.copies.values():
            for copies in srcs.values():
                yield copies


class MemMergePass(IRPass):
    dfg: DFGAnalysis
    _copies: _Copies

    # %1 = mload 5 => {%1: 5}
    # this represents the available loads, which have not been invalidated.
    _loads: dict[IRVariable, MemoryLocation]

    def run_pass(self, /, memory_abstract: bool):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.base_ptr = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.mem_alias = self.analyses_cache.request_analysis(MemoryAliasAnalysis)
        self.updater = InstUpdater(self.dfg)
        self.memory_abstract = memory_abstract

        for bb in self.function.get_basic_blocks():
            self._merge_mstore_dload(bb)
            self._handle_bb_memzero(bb)
            self._handle_bb(bb, "calldataload", "calldatacopy", CALLDATA, allow_dst_overlaps_src=True)
            self._handle_bb(bb, "dload", "dloadbytes", DATA, allow_dst_overlaps_src=True)

            if version_check(begin="cancun"):
                # mcopy is available
                self._handle_bb(bb, "mload", "mcopy", MEMORY)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _create_offset(self, inst: IRInstruction, loc: MemoryLocation) -> IROperand:
        assert loc.offset is not None
        if loc.is_concrete:
            return IRLiteral(loc.offset)

        assert loc.alloca is not None
        res = self.updater.add_before(inst, "add", [loc.alloca.inst.output, IRLiteral(loc.offset)])
        assert res is not None
        return res
        

    def _flush_copies(
        self, bb: IRBasicBlock, copies: list[_Copy], copy_opcode: str, load_opcode: str
    ):
        for copy in copies:
            copy.insts.sort(key=bb.instructions.index)

            pin_inst = None
            inst = copy.insts[-1]
            if copy.length != 32 or load_opcode == "dload":
                ops: list[IROperand] = [
                    IRLiteral(copy.length),
                    self._create_offset(inst, copy.src_loc),
                    self._create_offset(inst, copy.dst_loc),
                ]
                self.updater.update(inst, copy_opcode, ops)
            elif inst.opcode == "mstore":
                # we already have a load which is the val for this mstore;
                # leave it in place.
                var, _ = inst.operands
                assert isinstance(var, IRVariable)  # help mypy
                pin_inst = self.dfg.get_producing_instruction(var)
                assert pin_inst is not None  # help mypy

            else:
                # we are converting an mcopy into an mload+mstore (mload+mstore
                # is 1 byte smaller than mcopy).
                val = self.updater.add_before(inst, load_opcode, [self._create_offset(inst, copy.src_loc)])
                assert val is not None  # help mypy
                self.updater.update(inst, "mstore", [val, self._create_offset(inst, copy.dst_loc)])

            to_nop: list[IRInstruction] = []

            for inst in copy.insts[:-1]:
                if inst.opcode == load_opcode:
                    if inst is pin_inst:
                        continue

                    # if the load is used by any instructions besides the ones
                    # we are removing, we can't delete it. (in the future this
                    # may be handled by "remove unused effects" pass).
                    uses = self.dfg.get_uses(inst.output)
                    if not all(use in copy.insts for use in uses):
                        continue

                to_nop.append(inst)

            self.updater.nop_multi(to_nop)

        # need copy, since `copies` might be the same object as `self._copies`
        for c in copies.copy():
            self._copies.remove(c)

    def _invalidate_loads(self, loc: MemoryLocation):
        for var, ptr in self._loads.copy().items():
            if self.mem_alias.may_alias(ptr, loc):
                del self._loads[var]

    def _write_after_write_hazards(self, new_copy: _Copy) -> list[_Copy]:
        """
        check if there is an ordering hazard between new_copy
        and anything in self._copies. if new_copy and any existing
        copy write to the same destination, we need to preserve
        both writes (unless they can be fused into a single copy).
        """
        res = []
        for copy in self._copies.get_writes_to(new_copy.dst_loc.alloca):
            if copy.is_compatible(new_copy) and (copy.can_merge(new_copy) or new_copy.can_merge(copy)):
                # safe
                continue

            # note, these are the same:
            # - new_copy.overwrites(copy.dst_interval())
            # - copy.overwrites(new_copy.dst_interval())
            if new_copy.overwrites(copy.dst_loc):
                res.append(copy)

        return res

    def _read_after_write_hazards(self, new_copy: _Copy) -> list[_Copy]:
        """
        check if any copies in self._copies overwrite the read interval
        of new_copy
        """
        return self._copies_that_overwrite(new_copy.src_loc)

    def _write_after_read_hazards(self, new_copy: _Copy) -> list[_Copy]:
        """
        check if new_copy overwrites the read interval of anything in
        self._copies
        """
        res = []
        for copy in self._copies.get_reads_from(new_copy.dst_loc.alloca):
            if new_copy.overwrites(copy.src_loc):
                res.append(copy)

        return res

    def _add_copy(self, new_copy: _Copy):
        self._copies.insert(new_copy)

    def _copies_that_overwrite(self, read_interval: MemoryLocation) -> list[_Copy]:
        # check if any of self._copies tramples the interval
        res = []
        for copy in self._copies.get_writes_to(read_interval.alloca):
            if copy.overwrites(read_interval):
                res.append(copy)
        return res

    def _handle_bb(
        self,
        bb: IRBasicBlock,
        load_opcode: str,
        copy_opcode: str,
        addr_space: AddrSpace,
        allow_dst_overlaps_src: bool = False,
    ):
        self._loads = {}
        self._copies = _Copies(self.memory_abstract if addr_space == MEMORY else False)

        def _hard_barrier():
            # hard barrier. flush everything
            for copies in self._copies.get_all_lists():
                _barrier_for(copies)
                assert len(copies) == 0
            self._loads.clear()

        def _barrier_for(copies: list[_Copy]):
            self._flush_copies(bb, copies, copy_opcode, load_opcode)

        # copy in necessary because there is a possibility
        # of insertion in optimizations
        for inst in bb.instructions.copy():
            if inst.opcode == load_opcode:
                src_loc = self.base_ptr.get_read_location(inst, addr_space)
                if not src_loc.is_fixed:
                    _hard_barrier()
                    continue

                # flush any existing copies that trample read_interval
                if not allow_dst_overlaps_src:
                    copies = self._copies_that_overwrite(src_loc)
                    if len(copies) > 0:
                        _barrier_for(copies)

                self._loads[inst.output] = src_loc

            elif inst.opcode == "mstore":
                var, _ = inst.operands
                dst_loc = self.base_ptr.get_write_location(inst, MEMORY)

                if not isinstance(var, IRVariable) or not dst_loc.is_fixed:
                    _hard_barrier()
                    continue

                # unknown memory (not writing the result of an available load)
                if var not in self._loads:
                    _hard_barrier()
                    continue

                src_loc = self._loads[var]

                if not allow_dst_overlaps_src:
                    self._invalidate_loads(dst_loc)

                load_inst = self.dfg.get_producing_instruction(var)
                assert load_inst is not None  # help mypy
                n_copy = _Copy(dst_loc, src_loc, [inst, load_inst])

                write_hazards = self._write_after_write_hazards(n_copy)
                if len(write_hazards) > 0:
                    _barrier_for(write_hazards)

                # for mem2mem, we need to check if n_copy overwrites any
                # existing copies, or if any existing copies overwrite n_copy.
                if not allow_dst_overlaps_src:
                    read_hazards = self._read_after_write_hazards(n_copy)
                    # we are performing a store, so it's impossible to have a
                    # read hazard. (if a read hazard happened, it was already
                    # handled when we handled the load instruction).
                    assert len(read_hazards) == 0, "read hazard should never happened here"

                    read_hazards = self._write_after_read_hazards(n_copy)
                    if len(read_hazards) > 0:
                        _barrier_for(read_hazards)
                
                self._add_copy(n_copy)

            elif inst.opcode == copy_opcode:
                src_loc = self.base_ptr.get_read_location(inst, addr_space)
                dst_loc = self.base_ptr.get_write_location(inst, MEMORY)
                if not dst_loc.is_fixed or not src_loc.is_fixed:
                    _hard_barrier()
                    continue

                n_copy = _Copy(dst_loc, src_loc, [inst])
                if not allow_dst_overlaps_src:
                    self._invalidate_loads(dst_loc)

                write_hazards = self._write_after_write_hazards(n_copy)
                if len(write_hazards) > 0:
                    _barrier_for(write_hazards)

                # for mem2mem, we need to check if n_copy overwrites any
                # existing copies, or if any existing copies overwrite n_copy.
                if not allow_dst_overlaps_src:
                    read_hazards = self._read_after_write_hazards(n_copy)
                    if len(read_hazards) > 0:
                        _barrier_for(read_hazards)
                    read_hazards = self._write_after_read_hazards(n_copy)
                    if len(read_hazards) > 0:
                        _barrier_for(read_hazards)
                self._add_copy(n_copy)

            elif _volatile_memory(inst):
                _hard_barrier()

        _hard_barrier()

    # optimize memzeroing operations
    def _optimize_memzero(self, bb: IRBasicBlock):
        for copies in self._copies.get_all_lists():
            for copy in copies:
                inst = copy.insts[-1]
                if copy.length == 32:
                    new_ops: list[IROperand] = [IRLiteral(0), IRLiteral(copy.dst)]
                    self.updater.update(inst, "mstore", new_ops)
                else:
                    calldatasize = self.updater.add_before(inst, "calldatasize", [])
                    assert calldatasize is not None  # help mypy
                    new_ops = [IRLiteral(copy.length), calldatasize, IRLiteral(copy.dst)]
                    self.updater.update(inst, "calldatacopy", new_ops)

                for inst in copy.insts[:-1]:
                    self.updater.nop(inst)

        self._copies = _Copies(False)
        self._loads.clear()

    def _handle_bb_memzero(self, bb: IRBasicBlock):
        self._loads = {}
        self._copies = _Copies(self.memory_abstract)

        def _barrier():
            self._optimize_memzero(bb)

        # copy in necessary because there is a possibility
        # of insertion in optimizations
        for inst in bb.instructions.copy():
            if inst.opcode == "mstore":
                val = inst.operands[0]
                dst_loc = self.base_ptr.get_write_location(inst, MEMORY)
                is_zero_literal = isinstance(val, IRLiteral) and val.value == 0
                if not (dst_loc.is_fixed and is_zero_literal):
                    _barrier()
                    continue
                n_copy = _Copy.memzero(dst_loc, [inst])
                assert len(self._write_after_write_hazards(n_copy)) == 0
                self._add_copy(n_copy)
            elif inst.opcode == "calldatacopy":
                length, var, _ = inst.operands
                if not isinstance(var, IRVariable):
                    _barrier()
                    continue
                dst_loc = self.base_ptr.get_write_location(inst, MEMORY)
                if not dst_loc.is_fixed or not isinstance(length, IRLiteral):
                    _barrier()
                    continue
                src_inst = self.dfg.get_producing_instruction(var)
                assert src_inst is not None, f"bad variable {var}"
                if src_inst.opcode != "calldatasize":
                    _barrier()
                    continue
                n_copy = _Copy.memzero(dst_loc, [inst])
                assert len(self._write_after_write_hazards(n_copy)) == 0
                self._add_copy(n_copy)
            elif _volatile_memory(inst):
                _barrier()
                continue

        _barrier()

    # This pass is necessary for trivial cases of dload/mstore merging
    # where the src and dst pointers are variables, which are not handled
    # in the other merging passes.
    def _merge_mstore_dload(self, bb: IRBasicBlock):
        for inst in bb.instructions:
            if inst.opcode != "dload":
                continue

            dload = inst
            src = dload.operands[0]

            dload_out = dload.output
            uses = self.dfg.get_uses(dload_out)
            if len(uses) == 1:
                mstore: IRInstruction = uses.first()
                if mstore.opcode != "mstore":
                    continue
                _, dst = mstore.operands
                # merge simple
                self.updater.update(mstore, "dloadbytes", [IRLiteral(32), src, dst])
                self.updater.nop(dload)
                continue

            # we can only merge when the mstore is the first instruction
            # that uses dload. If we would not restrain ourself to basic
            # block we would have to check if the mstore dominates all of
            # the other uses
            uses_bb = dload.parent.get_uses().get(dload_out, OrderedSet())
            if len(uses_bb) == 0:
                continue

            # relies on order of bb.get_uses!
            # if this invariant would be broken
            # it must be handled differently
            mstore = uses_bb.first()
            if mstore.opcode != "mstore":
                continue

            var, dst = mstore.operands

            if var != dload_out:
                continue
            new_var = bb.parent.get_next_variable()

            self.updater.add_before(mstore, "dloadbytes", [IRLiteral(32), src, dst])
            self.updater.update(mstore, "mload", [dst], new_output=new_var)

            mload = mstore  # clarity

            self.updater.move_uses(dload_out, mload)
            self.updater.nop(dload)


def _volatile_memory(inst):
    inst_effects = inst.get_read_effects() | inst.get_write_effects()
    return Effects.MEMORY in inst_effects
