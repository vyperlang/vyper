from bisect import bisect_left
from dataclasses import dataclass

from vyper.evm.opcodes import version_check
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import IRPass


@dataclass
class _Interval:
    src_start: int
    src_end: int
    dst_start: int
    insts: list[IRInstruction]

    @property
    def length(self) -> int:
        return self.src_end - self.src_start

    @property
    def dst_end(self) -> int:
        return self.dst_start + self.length

    def self_overlap(self) -> bool:
        a = max(self.src_start, self.dst_start)
        b = min(self.src_end, self.dst_end)
        return a < b

    def overlap(self, other: "_Interval") -> bool:
        a = max(self.src_start, other.src_end)
        b = min(self.src_end, other.src_end)
        return a < b

    def add(self, src, dst, length, insts: list[IRInstruction]) -> bool:
        if src != self.src_end:
            return False
        if dst != self.dst_end:
            return False

        n_inter = _Interval(self.src_start, self.src_end + length, self.dst_start, [])
        if n_inter.self_overlap():
            return False

        self.src_end = n_inter.src_end
        self.insts.extend(insts)
        return True

    def copy(self) -> "_Interval":
        return _Interval(self.src_start, self.src_end, self.dst_start, self.insts)

    def merge(self, other: "_Interval") -> "_Interval | None":
        if self.src_start < other.src_start:
            n_inter = self.copy()
            if n_inter.add(other.src_start, other.dst_start, other.length, other.insts):
                return n_inter
            else:
                return None
        else:
            n_inter = other.copy()
            if n_inter.add(self.src_start, self.dst_start, self.length, self.insts):
                return n_inter
            else:
                return None

    def __lt__(self, other) -> bool:
        return self.src_start < other.src_start


class MemMergePass(IRPass):
    dfg: DFGAnalysis

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)  # type: ignore
        if not version_check(begin="cancun"):
            return

        for bb in self.function.get_basic_blocks():
            self._handle_bb(bb)

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _opt_intervals(self, bb: IRBasicBlock, intervals: list[_Interval]):
        for inter in intervals:
            if inter.length <= 32:
                continue
            inter.insts[0].output = None
            inter.insts[0].opcode = "mcopy"
            inter.insts[0].operands = [
                IRLiteral(inter.length),
                IRLiteral(inter.src_start),
                IRLiteral(inter.dst_start),
            ]
            for inst in inter.insts[1:]:
                bb.remove_instruction(inst)

        intervals.clear()

    def _add_interval(self, intervals: list[_Interval], new_inter: _Interval) -> bool:
        # print(intervals)
        # print(new_inter)
        if new_inter.self_overlap():
            # print("a")
            return False
        index = bisect_left(intervals, new_inter)
        if index == 0:
            if intervals[0].overlap(new_inter):
                # print("b")
                return False
            intervals.insert(0, new_inter)
            return True

        bef_inter = intervals[index - 1]
        merged = bef_inter.merge(new_inter)
        if merged is None:
            intervals.insert(index, new_inter)
            return True
        if merged.self_overlap():
            # print("c")
            return False
        if index < len(intervals) and merged.overlap(intervals[index]):
            # print("d")
            return False

        intervals[index - 1] = merged
        return True

    def _handle_bb(self, bb: IRBasicBlock):
        loads: dict[IRVariable, int] = dict()
        intervals: list[_Interval] = []

        for inst in bb.instructions:
            # if len(intervals) > 0:
            # print(intervals)
            if inst.opcode == "mload":
                src_op = inst.operands[0]
                if not isinstance(src_op, IRLiteral):
                    continue
                uses = self.dfg.get_uses(inst.output)  # type: ignore
                if len(uses) != 1:
                    continue
                if uses.first().opcode != "mstore":
                    continue
                assert isinstance(inst.output, IRVariable)
                loads[inst.output] = src_op.value
            elif inst.opcode == "mstore":
                var = inst.operands[0]
                dst = inst.operands[1]
                if not isinstance(dst, IRLiteral):
                    self._opt_intervals(bb, intervals)
                    loads.clear()
                    continue
                if not isinstance(var, IRVariable):
                    self._opt_intervals(bb, intervals)
                    loads.clear()
                    continue
                if var not in loads:
                    self._opt_intervals(bb, intervals)
                    loads.clear()
                    continue
                src: int = loads[var]
                n_inter = _Interval(
                    src,
                    src + 32,
                    dst.value,
                    [self.dfg.get_producing_instruction(var), inst],  # type: ignore
                )
                if len(intervals) == 0:
                    intervals.append(n_inter)
                else:
                    if not self._add_interval(intervals, n_inter):
                        self._opt_intervals(bb, intervals)
                        loads.clear()
            elif Effects.MEMORY in inst.get_write_effects():
                self._opt_intervals(bb, intervals)
                loads.clear()
        self._opt_intervals(bb, intervals)
