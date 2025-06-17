from bisect import bisect_left
from dataclasses import dataclass

from vyper.evm.opcodes import version_check
from vyper.utils import OrderedSet
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import InstUpdater, IRPass


@dataclass
class _Interval:
    start: int
    length: int

    @property
    def end(self):
        return self.start + self.length

    def overlaps(self, other):
        a = max(self.start, other.start)
        b = min(self.end, other.end)
        return a < b


@dataclass
class _Copy:
    # abstract "copy" operation which contains a list of copy instructions
    # and can fuse them into a single copy operation.
    dst: int
    src: int
    length: int
    insts: list[IRInstruction]

    @classmethod
    def memzero(cls, dst, length, insts):
        # factory method to simplify creation of memory zeroing operations
        # (which are similar to Copy operations but src is always
        # `calldatasize`). choose src=dst, so that can_merge returns True
        # for overlapping memzeros.
        return cls(dst, dst, length, insts)

    @property
    def src_end(self) -> int:
        return self.src + self.length

    @property
    def dst_end(self) -> int:
        return self.dst + self.length

    def src_interval(self) -> _Interval:
        return _Interval(self.src, self.length)

    def dst_interval(self) -> _Interval:
        return _Interval(self.dst, self.length)

    def overwrites_self_src(self) -> bool:
        # return true if dst overlaps src. this is important for blocking
        # mcopy batching in certain cases.
        return self.overwrites(self.src_interval())

    def overwrites(self, interval: _Interval) -> bool:
        # return true if dst of self overwrites the interval
        return _Interval(self.dst, self.length).overlaps(interval)

    def can_merge(self, other: "_Copy"):
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
        self.length = new_length
        self.insts.extend(other.insts)

    def __repr__(self) -> str:
        return f"_Copy({self.dst}, {self.src}, {self.length})"


class MemMergePass(IRPass):
    dfg: DFGAnalysis
    _copies: list[_Copy]

    # %1 = mload 5 => {%1: 5}
    # this represents the available loads, which have not been invalidated.
    _loads: dict[IRVariable, int]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        for bb in self.function.get_basic_blocks():
            self._merge_mstore_dload(bb)
            self._handle_bb_memzero(bb)
            self._handle_bb(bb, "calldataload", "calldatacopy", allow_dst_overlaps_src=True)
            self._handle_bb(bb, "dload", "dloadbytes", allow_dst_overlaps_src=True)

            if version_check(begin="cancun"):
                # mcopy is available
                self._handle_bb(bb, "mload", "mcopy")

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

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
                    IRLiteral(copy.src),
                    IRLiteral(copy.dst),
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
                val = self.updater.add_before(inst, load_opcode, [IRLiteral(copy.src)])
                assert val is not None  # help mypy
                self.updater.update(inst, "mstore", [val, IRLiteral(copy.dst)])

            to_nop: list[IRInstruction] = []

            for inst in copy.insts[:-1]:
                if inst.opcode == load_opcode:
                    if inst is pin_inst:
                        continue

                    # if the load is used by any instructions besides the ones
                    # we are removing, we can't delete it. (in the future this
                    # may be handled by "remove unused effects" pass).
                    assert isinstance(inst.output, IRVariable)  # help mypy
                    uses = self.dfg.get_uses(inst.output)
                    if not all(use in copy.insts for use in uses):
                        continue

                to_nop.append(inst)

            self.updater.nop_multi(to_nop)

        # need copy, since `copies` might be the same object as `self._copies`
        for c in copies.copy():
            self._copies.remove(c)

    def _invalidate_loads(self, interval: _Interval):
        for var, ptr in self._loads.copy().items():
            if _Interval(ptr, 32).overlaps(interval):
                del self._loads[var]

    def _write_after_write_hazards(self, new_copy: _Copy) -> list[_Copy]:
        """
        check if there is an ordering hazard between new_copy
        and anything in self._copies. if new_copy and any existing
        copy write to the same destination, we need to preserve
        both writes (unless they can be fused into a single copy).
        """
        res = []
        for copy in self._copies:
            if copy.can_merge(new_copy) or new_copy.can_merge(copy):
                # safe
                continue

            # note, these are the same:
            # - new_copy.overwrites(copy.dst_interval())
            # - copy.overwrites(new_copy.dst_interval())
            if new_copy.overwrites(copy.dst_interval()):
                res.append(copy)

        return res

    def _read_after_write_hazards(self, new_copy: _Copy) -> list[_Copy]:
        """
        check if any copies in self._copies overwrite the read interval
        of new_copy
        """
        return self._copies_that_overwrite(new_copy.src_interval())

    def _write_after_read_hazards(self, new_copy: _Copy) -> list[_Copy]:
        """
        check if new_copy overwrites the read interval of anything in
        self._copies
        """
        res = []
        for copy in self._copies:
            if new_copy.overwrites(copy.src_interval()):
                res.append(copy)

        return res

    def _find_insertion_point(self, new_copy: _Copy):
        return bisect_left(self._copies, new_copy.dst, key=lambda c: c.dst)

    def _add_copy(self, new_copy: _Copy):
        index = self._find_insertion_point(new_copy)
        self._copies.insert(index, new_copy)

        i = max(index - 1, 0)
        while i < min(index + 1, len(self._copies) - 1):
            if self._copies[i].can_merge(self._copies[i + 1]):
                self._copies[i].merge(self._copies[i + 1])
                del self._copies[i + 1]
            else:
                i += 1

    def _copies_that_overwrite(self, read_interval: _Interval) -> list[_Copy]:
        # check if any of self._copies tramples the interval
        return [c for c in self._copies if c.overwrites(read_interval)]

    def _handle_bb(
        self,
        bb: IRBasicBlock,
        load_opcode: str,
        copy_opcode: str,
        allow_dst_overlaps_src: bool = False,
    ):
        self._loads = {}
        self._copies = []

        def _hard_barrier():
            # hard barrier. flush everything
            _barrier_for(self._copies)
            assert len(self._copies) == 0
            self._loads.clear()

        def _barrier_for(copies: list[_Copy]):
            self._flush_copies(bb, copies, copy_opcode, load_opcode)

        # copy in necessary because there is a possibility
        # of insertion in optimizations
        for inst in bb.instructions.copy():
            if inst.opcode == load_opcode:
                src_op = inst.operands[0]
                if not isinstance(src_op, IRLiteral):
                    _hard_barrier()
                    continue

                read_interval = _Interval(src_op.value, 32)

                # flush any existing copies that trample read_interval
                if not allow_dst_overlaps_src:
                    copies = self._copies_that_overwrite(read_interval)
                    if len(copies) > 0:
                        _barrier_for(copies)

                assert inst.output is not None, inst
                self._loads[inst.output] = src_op.value

            elif inst.opcode == "mstore":
                var, dst = inst.operands

                if not isinstance(var, IRVariable) or not isinstance(dst, IRLiteral):
                    _hard_barrier()
                    continue

                # unknown memory (not writing the result of an available load)
                if var not in self._loads:
                    _hard_barrier()
                    continue

                src_ptr = self._loads[var]

                if not allow_dst_overlaps_src:
                    self._invalidate_loads(_Interval(dst.value, 32))

                load_inst = self.dfg.get_producing_instruction(var)
                assert load_inst is not None  # help mypy
                n_copy = _Copy(dst.value, src_ptr, 32, [inst, load_inst])

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
                if not all(isinstance(op, IRLiteral) for op in inst.operands):
                    _hard_barrier()
                    continue

                length, src, dst = inst.operands
                n_copy = _Copy(dst.value, src.value, length.value, [inst])
                if not allow_dst_overlaps_src:
                    self._invalidate_loads(_Interval(dst.value, length.value))

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
        for copy in self._copies:
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

        self._copies.clear()
        self._loads.clear()

    def _handle_bb_memzero(self, bb: IRBasicBlock):
        self._loads = {}
        self._copies = []

        def _barrier():
            self._optimize_memzero(bb)

        # copy in necessary because there is a possibility
        # of insertion in optimizations
        for inst in bb.instructions.copy():
            if inst.opcode == "mstore":
                val = inst.operands[0]
                dst = inst.operands[1]
                is_zero_literal = isinstance(val, IRLiteral) and val.value == 0
                if not (isinstance(dst, IRLiteral) and is_zero_literal):
                    _barrier()
                    continue
                n_copy = _Copy.memzero(dst.value, 32, [inst])
                assert len(self._write_after_write_hazards(n_copy)) == 0
                self._add_copy(n_copy)
            elif inst.opcode == "calldatacopy":
                length, var, dst = inst.operands
                if not isinstance(var, IRVariable):
                    _barrier()
                    continue
                if not isinstance(dst, IRLiteral) or not isinstance(length, IRLiteral):
                    _barrier()
                    continue
                src_inst = self.dfg.get_producing_instruction(var)
                assert src_inst is not None, f"bad variable {var}"
                if src_inst.opcode != "calldatasize":
                    _barrier()
                    continue
                n_copy = _Copy.memzero(dst.value, length.value, [inst])
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

            assert dload.output is not None
            uses = self.dfg.get_uses(dload.output)
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
            uses_bb = dload.parent.get_uses().get(dload.output, OrderedSet())
            if len(uses_bb) == 0:
                continue

            # relies on order of bb.get_uses!
            # if this invariant would be broken
            # it must be handled differently
            mstore = uses_bb.first()
            if mstore.opcode != "mstore":
                continue

            var, dst = mstore.operands

            if var != dload.output:
                continue

            assert isinstance(var, IRVariable)  # help mypy
            new_var = bb.parent.get_next_variable()

            self.updater.add_before(mstore, "dloadbytes", [IRLiteral(32), src, dst])
            self.updater.update(mstore, "mload", [dst], new_output=new_var)

            mload = mstore  # clarity

            self.updater.move_uses(dload.output, mload)
            self.updater.nop(dload)


def _volatile_memory(inst):
    inst_effects = inst.get_read_effects() | inst.get_write_effects()
    return Effects.MEMORY in inst_effects or Effects.MSIZE in inst_effects
