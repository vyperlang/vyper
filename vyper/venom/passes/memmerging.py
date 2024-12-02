from bisect import bisect_left
from dataclasses import dataclass

from vyper.evm.opcodes import version_check
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import IRPass


@dataclass
class _Interval:
    dst_start: int
    src_start: int
    length: int
    insts: list[IRInstruction]

    @property
    def src_end(self) -> int:
        return self.src_start + self.length

    @property
    def dst_end(self) -> int:
        return self.dst_start + self.length

    def dst_overlaps_src(self) -> bool:
        # return true if dst overlaps src. this is important for blocking
        # mcopy batching in certain cases.
        a = max(self.src_start, self.dst_start)
        b = min(self.src_end, self.dst_end)
        return a < b

    def overlap(self, other: "_Interval") -> bool:
        a = max(self.src_start, other.src_start)
        b = min(self.src_end, other.src_end)
        return a < b

    def merge(self, other: "_Interval", ok_dst_overlap: bool) -> bool:
        assert self.src_start <= other.src_start, "bad bisect_left"
        if other.src_start != self.src_end:
            return False
        if other.dst_start != self.dst_end:
            return False

        n_inter = _Interval(self.dst_start, self.src_start, self.length + other.length, [])
        if not ok_dst_overlap and n_inter.dst_overlaps_src():
            return False

        self.length = n_inter.length
        self.insts.extend(other.insts)
        return True

    def __lt__(self, other) -> bool:
        return self.src_start < other.src_start

    def __repr__(self) -> str:
        return (
            f"({self.src_start}, {self.src_end}, {self.length}, {self.dst_start}, {self.dst_end})"
        )


class MemMergePass(IRPass):
    dfg: DFGAnalysis

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)  # type: ignore

        for bb in self.function.get_basic_blocks():
            self._handle_bb_memzero(bb)
            self._handle_bb(bb, "calldataload", "calldatacopy")

            if version_check(begin="cancun"):
                # mcopy is available
                self._handle_bb(bb, "mload", "mcopy")

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _optimize_copy(self, bb: IRBasicBlock, intervals: list[_Interval], copy_inst: str):
        for inter in intervals:
            if inter.length <= 32:
                continue

            inter.insts[-1].output = None
            inter.insts[-1].opcode = copy_inst
            inter.insts[-1].operands = [
                IRLiteral(inter.length),
                IRLiteral(inter.src_start),
                IRLiteral(inter.dst_start),
            ]
            for inst in inter.insts[0:-1]:
                bb.remove_instruction(inst)

        intervals.clear()

    def _add_interval(
        self, intervals: list[_Interval], new_inter: _Interval, allow_dst_overlap_src: bool = False
    ) -> bool:
        if not allow_dst_overlap_src and new_inter.dst_overlaps_src():
            return False
        index = bisect_left(intervals, new_inter)
        if self._overlap_exist(intervals, new_inter, index = index):
            return False
        intervals.insert(index, new_inter)

        i = max(index - 1, 0)
        while i < min(index + 1, len(intervals) - 1):
            merged = intervals[i].merge(intervals[i + 1], allow_dst_overlap_src)
            if merged:
                del intervals[i + 1]
            else:
                i += 1

        return True

    def _overlap_exist(self, intervals: list[_Interval], inter: _Interval, index: int | None = None) -> bool:
        if index is None:
            index = bisect_left(intervals, inter)

        if index > 0:
            if intervals[index - 1].overlap(inter):
                return True

        if index < len(intervals):
            if intervals[index].overlap(inter):
                return True

        return False

    def _handle_bb(
        self, bb: IRBasicBlock, load_inst: str, copy_inst: str, allow_dst_overlaps_src: bool = False
    ):
        loads: dict[IRVariable, int] = dict()
        intervals: list[_Interval] = []

        def _barrier():
            self._optimize_copy(bb, intervals, copy_inst)
            loads.clear()

        for inst in bb.instructions.copy():
            if inst.opcode == load_inst:
                src_op = inst.operands[0]
                if not isinstance(src_op, IRLiteral):
                    _barrier()
                    continue
                assert inst.output is not None  # help mypy
                uses = self.dfg.get_uses(inst.output)
                if len(uses) != 1:
                    _barrier()
                    continue
                if uses.first().opcode != "mstore":
                    _barrier()
                    continue
                if self._overlap_exist(
                    intervals, _Interval(src_op.value + 32, src_op.value, 32, [])
                ):
                    _barrier()
                    continue
                assert isinstance(inst.output, IRVariable)
                loads[inst.output] = src_op.value
            elif inst.opcode == "mstore":
                var = inst.operands[0]
                dst = inst.operands[1]
                if not isinstance(dst, IRLiteral) or not isinstance(var, IRVariable):
                    _barrier()
                    continue
                if var not in loads:
                    _barrier()
                    continue
                src: int = loads[var]
                mload_inst = self.dfg.get_producing_instruction(var)
                assert mload_inst is not None  # help mypy
                n_inter = _Interval(dst.value, src, 32, [mload_inst, inst])
                if not self._add_interval(
                    intervals, n_inter, allow_dst_overlap_src=allow_dst_overlaps_src
                ):
                    _barrier()
            elif _volatile_memory(inst):
                _barrier()

        self._optimize_copy(bb, intervals, copy_inst)

    # optimize memzeroing operations
    def _optimize_memzero(self, bb: IRBasicBlock, intervals: list[_Interval]):
        for interval in intervals:
            inst = interval.insts[-1]
            if interval.length == 32 and inst.opcode == "calldatacopy":
                inst.opcode = "mstore"
                inst.operands = [IRLiteral(0), IRLiteral(interval.dst_start)]
            elif interval.length == 32:
                continue
            else:
                index = bb.instructions.index(inst)
                calldatasize = bb.parent.get_next_variable()
                bb.insert_instruction(IRInstruction("calldatasize", [], output=calldatasize), index)

                inst.output = None
                inst.opcode = "calldatacopy"
                inst.operands = [
                    IRLiteral(interval.length),
                    calldatasize,
                    IRLiteral(interval.dst_start),
                ]
            for inst in interval.insts[0:-1]:
                bb.remove_instruction(inst)

        intervals.clear()

    def _handle_bb_memzero(self, bb: IRBasicBlock):
        loads: dict[IRVariable, int] = {}
        intervals: list[_Interval] = []

        def _barrier():
            self._optimize_memzero(bb, intervals)
            loads.clear()

        for inst in bb.instructions.copy():
            if inst.opcode == "mstore":
                val = inst.operands[0]
                dst = inst.operands[1]
                is_zero_literal = isinstance(val, IRLiteral) and val.value == 0
                if not (isinstance(dst, IRLiteral) and is_zero_literal):
                    _barrier()
                    continue
                n_inter = _Interval(dst.value, dst.value, 32, [inst])
                if not self._add_interval(intervals, n_inter, allow_dst_overlap_src=True):
                    _barrier()
            elif inst.opcode == "calldatacopy":
                dst, var, length = inst.operands[2], inst.operands[1], inst.operands[0]
                if not isinstance(dst, IRLiteral):
                    continue
                if not isinstance(length, IRLiteral):
                    continue
                if not isinstance(var, IRVariable):
                    continue
                src_inst = self.dfg.get_producing_instruction(var)
                if src_inst is None or src_inst.opcode != "calldatasize":
                    continue
                n_inter = _Interval(dst.value, dst.value, length.value, [inst])
                if not self._add_interval(intervals, n_inter, allow_dst_overlap_src=True):
                    _barrier()
            elif _volatile_memory(inst):
                _barrier()
        self._optimize_memzero(bb, intervals)


def _volatile_memory(inst):
    inst_effects = inst.get_read_effects() | inst.get_write_effects()
    return Effects.MEMORY in inst_effects or Effects.MSIZE in inst_effects
