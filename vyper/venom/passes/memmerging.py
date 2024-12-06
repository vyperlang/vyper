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

    @property
    def src_end(self) -> int:
        return self.src + self.length

    @property
    def dst_end(self) -> int:
        return self.dst + self.length

    def src_interval(self) -> _Interval:
        return _Interval(self.src, self.length)

    def overwrites_self_src(self) -> bool:
        # return true if dst overlaps src. this is important for blocking
        # mcopy batching in certain cases.
        return self.overwrites(self.src_interval())

    def overwrites(self, interval: _Interval) -> bool:
        # return true if dst of self overwrites src of the other.
        a = max(self.dst, interval.start)
        b = min(self.dst_end, interval.end)
        return a < b

    def merge(self, other: "_Copy") -> bool:
        assert self.dst <= other.dst, "bad bisect_left"
        # merge other into self. e.g.
        # Copy(0, 64, 16); Copy(16, 80, 8) => Copy(0, 64, 24)

        # both source and destination have to be offset by same amount,
        # otherwise they do not represent the same copy. e.g.
        # Copy(0, 64, 16)
        # Copy(11, 74, 16)
        if self.src - other.src != self.dst - other.dst:
            return False

        # the copies must at least touch each other
        if other.src > self.src_end:
            return False

        new_length = max(self.src_end, other.src_end) - self.src
        self.length = new_length
        self.insts.extend(other.insts)
        return True

    def __lt__(self, other) -> bool:
        return self.dst < other.dst

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

            if version_check(begin="cancun"):
                # mcopy is available
                self._handle_bb(bb, "mload", "mcopy")

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _optimize_copy(self, bb: IRBasicBlock, copy_opcode: str, load_opcode: str):
        for copy in self._copies:
            if copy_opcode == "mcopy":
                assert not copy.overwrites_self_src()
            if copy.length == 32:
                inst = copy.insts[0]
                index = inst.parent.instructions.index(inst)
                var = bb.parent.get_next_variable()
                load = IRInstruction(load_opcode, [IRLiteral(copy.src)], output=var)
                inst.parent.insert_instruction(load, index)

                inst.opcode = "mstore"
                inst.output = None
                inst.operands = [var, IRLiteral(copy.dst)]
            else:
                copy.insts[0].output = None
                copy.insts[0].opcode = copy_opcode
                copy.insts[0].operands = [
                    IRLiteral(copy.length),
                    IRLiteral(copy.src),
                    IRLiteral(copy.dst),
                ]

            for inst in copy.insts[1:]:
                if inst.opcode == load_opcode:
                    # if the load is used by anything but an mstore, we can't
                    # delete it. (in the future this may be handled by "remove
                    # unused effects" pass).
                    assert inst.output is not None  # help mypy
                    uses = self.dfg.get_uses(inst.output)
                    if len(uses) != 1:
                        continue
                    if uses.first().opcode != "mstore":
                        continue

                bb.mark_for_removal(inst)

        self._copies.clear()
        self._loads.clear()

    def _add_copy_allowed(self, new_copy: _Copy) -> bool:
        new_copies = self._copies + [new_copy]
        if any(new_copy.overwrites(copy.src_interval()) for copy in new_copies):
            return False
        for _, load_ptr in self._loads.items():
            read_interval = _Interval(load_ptr, 32)
            if self._overwrites(read_interval):
                return False
        return True

    def _add_copy(self, new_copy: _Copy):
        index = bisect_left(self._copies, new_copy)
        self._copies.insert(index, new_copy)

        i = max(index - 1, 0)
        while i < min(index + 1, len(self._copies) - 1):
            merged = self._copies[i].merge(self._copies[i + 1])
            if merged:
                del self._copies[i + 1]
            else:
                i += 1

    def _overwrites(self, inter: _Interval) -> bool:
        # check if any of self._copies tramples the interval

        # could use bisect_left to optimize, but it's harder to reason about
        return any(c.overwrites(inter) for c in self._copies)

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

        for inst in bb.instructions:
            if inst.opcode == load_opcode:
                src_op = inst.operands[0]
                if not isinstance(src_op, IRLiteral):
                    _barrier()
                    continue

                load_ptr = src_op.value
                read_interval = _Interval(load_ptr, 32)
                if not allow_dst_overlaps_src and self._overwrites(read_interval):
                    _barrier()
                    continue

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

                # check if the new copy does not overwrites existing data
                if not allow_dst_overlaps_src and not self._add_copy_allowed(n_copy):
                    _barrier()
                    continue
                self._add_copy(n_copy)

            elif inst.opcode == copy_opcode:
                if not all(isinstance(op, IRLiteral) for op in inst.operands):
                    _barrier()
                    continue

                length, src, dst = inst.operands
                n_copy = _Copy(dst.value, src.value, length.value, [inst])
                if self._overwrites(n_copy.src_interval()):
                    _barrier()
                    continue

                # check if the new copy does not overwrites existing data
                if not allow_dst_overlaps_src and not self._add_copy_allowed(n_copy):
                    _barrier()
                    continue
                self._add_copy(n_copy)

            elif _volatile_memory(inst):
                _barrier()

        _barrier()
        bb.clear_dead_instructions()

    # optimize memzeroing operations
    def _optimize_memzero(self, bb: IRBasicBlock):
        for copy in self._copies:
            inst = copy.insts[0]
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

            for inst in copy.insts[1:]:
                bb.mark_for_removal(inst)

        self._copies.clear()
        self._loads.clear()

    def _handle_bb_memzero(self, bb: IRBasicBlock):
        self._loads = {}
        self._copies = []

        def _barrier():
            self._optimize_memzero(bb)

        for inst in bb.instructions:
            if inst.opcode == "mstore":
                val = inst.operands[0]
                dst = inst.operands[1]
                is_zero_literal = isinstance(val, IRLiteral) and val.value == 0
                if not (isinstance(dst, IRLiteral) and is_zero_literal):
                    _barrier()
                    continue
                n_copy = _Copy(dst.value, dst.value, 32, [inst])
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
                n_copy = _Copy(dst.value, dst.value, length.value, [inst])
                self._add_copy(n_copy)
            elif _volatile_memory(inst):
                _barrier()
                continue

        _barrier()
        bb.clear_dead_instructions()


def _volatile_memory(inst):
    inst_effects = inst.get_read_effects() | inst.get_write_effects()
    return Effects.MEMORY in inst_effects or Effects.MSIZE in inst_effects
