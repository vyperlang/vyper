from bisect import bisect_left
from dataclasses import dataclass

from vyper.evm.opcodes import version_check
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import IRPass


@dataclass
class _Interval:
    start: int
    length: int

    @property
    def end(self):
        return self.start + self.length


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
        a = max(self.dst, interval.start)
        b = min(self.dst_end, interval.end)
        return a < b

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
        return f"({self.src}, {self.src_end}, {self.length}, {self.dst}, {self.dst_end})"


class MemMergePass(IRPass):
    dfg: DFGAnalysis
    _copies: list[_Copy]
    _loads: dict[IRVariable, int]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)  # type: ignore

        for bb in self.function.get_basic_blocks():
            self._handle_bb_memzero(bb)
            self._handle_bb(bb, "calldataload", "calldatacopy", allow_dst_overlaps_src=True)
            self._handle_bb(bb, "dload", "dloadbytes", allow_dst_overlaps_src=True)

            if version_check(begin="cancun"):
                # mcopy is available
                self._handle_bb(bb, "mload", "mcopy")

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _optimize_copy(self, bb: IRBasicBlock, copy_opcode: str, load_opcode: str):
        for copy in self._copies:
            copy.insts.sort(key=bb.instructions.index)

            if copy_opcode == "mcopy":
                assert not copy.overwrites_self_src()

            pin_inst = None
            inst = copy.insts[-1]
            if copy.length != 32 or load_opcode == "dload":
                inst.output = None
                inst.opcode = copy_opcode
                inst.operands = [IRLiteral(copy.length), IRLiteral(copy.src), IRLiteral(copy.dst)]
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
                index = inst.parent.instructions.index(inst)
                var = bb.parent.get_next_variable()
                load = IRInstruction(load_opcode, [IRLiteral(copy.src)], output=var)
                inst.parent.insert_instruction(load, index)

                inst.output = None
                inst.opcode = "mstore"
                inst.operands = [var, IRLiteral(copy.dst)]

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

                inst.make_nop()

        self._copies.clear()
        self._loads.clear()

    def _write_after_write_hazard(self, new_copy: _Copy) -> bool:
        for copy in self._copies:
            # note, these are the same:
            # - new_copy.overwrites(copy.dst_interval())
            # - copy.overwrites(new_copy.dst_interval())
            if new_copy.overwrites(copy.dst_interval()) and not (
                copy.can_merge(new_copy) or new_copy.can_merge(copy)
            ):
                return True
        return False

    def _read_after_write_hazard(self, new_copy: _Copy) -> bool:
        new_copies = self._copies + [new_copy]

        # new copy would overwrite memory that
        # needs to be read to optimize copy
        if any(new_copy.overwrites(copy.src_interval()) for copy in new_copies):
            return True

        # existing copies would overwrite memory that the
        # new copy would need
        if self._overwrites(new_copy.src_interval()):
            return True

        return False

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

    def _overwrites(self, read_interval: _Interval) -> bool:
        # check if any of self._copies tramples the interval

        # could use bisect_left to optimize, but it's harder to reason about
        return any(c.overwrites(read_interval) for c in self._copies)

    def _handle_bb(
        self,
        bb: IRBasicBlock,
        load_opcode: str,
        copy_opcode: str,
        allow_dst_overlaps_src: bool = False,
    ):
        self._loads = {}
        self._copies = []

        def _barrier():
            self._optimize_copy(bb, copy_opcode, load_opcode)

        # copy in necessary because there is a possibility
        # of insertion in optimizations
        for inst in bb.instructions.copy():
            if inst.opcode == load_opcode:
                src_op = inst.operands[0]
                if not isinstance(src_op, IRLiteral):
                    _barrier()
                    continue

                read_interval = _Interval(src_op.value, 32)

                # we will read from this memory so we need to put barier
                if not allow_dst_overlaps_src and self._overwrites(read_interval):
                    _barrier()

                assert inst.output is not None
                self._loads[inst.output] = src_op.value

            elif inst.opcode == "mstore":
                var, dst = inst.operands

                if not isinstance(var, IRVariable) or not isinstance(dst, IRLiteral):
                    _barrier()
                    continue

                if var not in self._loads:
                    _barrier()
                    continue

                src_ptr = self._loads[var]
                load_inst = self.dfg.get_producing_instruction(var)
                assert load_inst is not None  # help mypy
                n_copy = _Copy(dst.value, src_ptr, 32, [inst, load_inst])

                if self._write_after_write_hazard(n_copy):
                    _barrier()
                    # no continue needed, we have not invalidated the loads dict

                # check if the new copy does not overwrites existing data
                if not allow_dst_overlaps_src and self._read_after_write_hazard(n_copy):
                    _barrier()
                    # this continue is necessary because we have invalidated
                    # the _loads dict, so src_ptr is no longer valid.
                    continue
                self._add_copy(n_copy)

            elif inst.opcode == copy_opcode:
                if not all(isinstance(op, IRLiteral) for op in inst.operands):
                    _barrier()
                    continue

                length, src, dst = inst.operands
                n_copy = _Copy(dst.value, src.value, length.value, [inst])

                if self._write_after_write_hazard(n_copy):
                    _barrier()
                # check if the new copy does not overwrites existing data
                if not allow_dst_overlaps_src and self._read_after_write_hazard(n_copy):
                    _barrier()
                self._add_copy(n_copy)

            elif _volatile_memory(inst):
                _barrier()

        _barrier()

    # optimize memzeroing operations
    def _optimize_memzero(self, bb: IRBasicBlock):
        for copy in self._copies:
            inst = copy.insts[-1]
            if copy.length == 32:
                inst.opcode = "mstore"
                inst.operands = [IRLiteral(0), IRLiteral(copy.dst)]
            else:
                index = bb.instructions.index(inst)
                calldatasize = bb.parent.get_next_variable()
                bb.insert_instruction(IRInstruction("calldatasize", [], output=calldatasize), index)

                inst.output = None
                inst.opcode = "calldatacopy"
                inst.operands = [IRLiteral(copy.length), calldatasize, IRLiteral(copy.dst)]

            for inst in copy.insts[:-1]:
                inst.make_nop()

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
                assert not self._write_after_write_hazard(n_copy)
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
                assert not self._write_after_write_hazard(n_copy)
                self._add_copy(n_copy)
            elif _volatile_memory(inst):
                _barrier()
                continue

        _barrier()


def _volatile_memory(inst):
    inst_effects = inst.get_read_effects() | inst.get_write_effects()
    return Effects.MEMORY in inst_effects or Effects.MSIZE in inst_effects
