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

    def add(
        self, src, dst, length, insts: list[IRInstruction], ok_self_overlap: bool = False
    ) -> bool:
        if src != self.src_end:
            return False
        if dst != self.dst_end:
            return False

        n_inter = _Interval(self.src_start, self.src_end + length, self.dst_start, [])
        if not ok_self_overlap and n_inter.self_overlap():
            return False

        self.src_end = n_inter.src_end
        self.insts.extend(insts)
        return True

    def copy(self) -> "_Interval":
        return _Interval(self.src_start, self.src_end, self.dst_start, self.insts)

    def merge(self, other: "_Interval", ok_self_overlap: bool) -> "_Interval | None":
        if self.src_start < other.src_start:
            n_inter = self.copy()
            if n_inter.add(
                other.src_start, other.dst_start, other.length, other.insts, ok_self_overlap
            ):
                return n_inter
            else:
                return None
        else:
            n_inter = other.copy()
            if n_inter.add(
                self.src_start, self.dst_start, self.length, self.insts, ok_self_overlap
            ):
                return n_inter
            else:
                return None

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
            self._handle_bb_zeroing(bb)
            self._handle_bb(bb, "calldataload", "calldatacopy")
            if not version_check(begin="cancun"):
                continue
            self._handle_bb(bb, "mload", "mcopy")

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _opt_intervals(self, bb: IRBasicBlock, intervals: list[_Interval], copy_inst: str):
        for inter in intervals:
            if inter.length <= 32:
                continue
            inter.insts[0].output = None
            inter.insts[0].opcode = copy_inst
            inter.insts[0].operands = [
                IRLiteral(inter.length),
                IRLiteral(inter.src_start),
                IRLiteral(inter.dst_start),
            ]
            for inst in inter.insts[1:]:
                bb.remove_instruction(inst)

        intervals.clear()

    def _add_interval(
        self, intervals: list[_Interval], new_inter: _Interval, ok_self_overlap: bool = False
    ) -> bool:
        if not ok_self_overlap and new_inter.self_overlap():
            return False
        index = bisect_left(intervals, new_inter)
        intervals.insert(index, new_inter)

        i = max(index - 1, 0)
        while i < min(index + 1, len(intervals) - 1):
            merged = intervals[i].merge(intervals[i + 1], ok_self_overlap)
            i += 1
            if merged is None:
                continue
            if not ok_self_overlap and merged.self_overlap():
                continue
            intervals[i - 1] = merged
            del intervals[i]

        return True

    def _handle_bb(self, bb: IRBasicBlock, load_inst: str, copy_inst: str):
        loads: dict[IRVariable, int] = dict()
        intervals: list[_Interval] = []

        def opt():
            self._opt_intervals(bb, intervals, copy_inst)
            loads.clear()

        for inst in bb.instructions:
            if inst.opcode == load_inst:
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
                if not (isinstance(dst, IRLiteral) and isinstance(var, IRVariable)):
                    opt()
                    continue
                if var not in loads:
                    opt()
                    continue
                src: int = loads[var]
                n_inter = _Interval(
                    src,
                    src + 32,
                    dst.value,
                    [self.dfg.get_producing_instruction(var), inst],  # type: ignore
                )
                if not self._add_interval(intervals, n_inter):
                    opt()
            # why wont this trigger some error
            elif False and Effects.MEMORY in inst.get_write_effects():
                self._opt_intervals(bb, intervals, copy_inst)
                loads.clear()
        self._opt_intervals(bb, intervals, copy_inst)

    def _zero_opt(self, bb: IRBasicBlock, intervals: list[_Interval]):
        for inter in intervals:
            if inter.length <= 32:
                continue
            index = bb.instructions.index(inter.insts[0])
            tmp_var = bb.parent.get_next_variable()
            bb.insert_instruction(IRInstruction("calldatasize", [], output=tmp_var), index)
            inter.insts[0].output = None
            inter.insts[0].opcode = "calldatacopy"
            inter.insts[0].operands = [IRLiteral(inter.length), tmp_var, IRLiteral(inter.dst_start)]
            for inst in inter.insts[1:]:
                bb.remove_instruction(inst)

        intervals.clear()

    def _handle_bb_zeroing(self, bb: IRBasicBlock):
        loads: dict[IRVariable, int] = dict()
        intervals: list[_Interval] = []

        def opt():
            self._zero_opt(bb, intervals)
            loads.clear()

        for inst in bb.instructions:
            if inst.opcode == "mstore":
                zero = inst.operands[0]
                dst = inst.operands[1]
                if not (
                    isinstance(dst, IRLiteral) and isinstance(zero, IRLiteral) and zero.value == 0
                ):
                    opt()
                    continue
                n_inter = _Interval(dst.value, dst.value + 32, dst.value, [inst])  # type: ignore
                if not self._add_interval(intervals, n_inter, ok_self_overlap=True):
                    opt()
            elif inst.opcode == "calldatacopy":
                dst, var, length = inst.operands[2], inst.operands[1], inst.operands[0]
                if not isinstance(dst, IRLiteral):
                    continue
                if not isinstance(length, IRLiteral):
                    continue
                if not isinstance(var, IRVariable):
                    continue
                src_inst = self.dfg.get_producing_instruction(var)
                if src_inst is None:
                    continue
                if src_inst.opcode != "calldatasize":
                    continue
                n_inter = _Interval(
                    dst.value, dst.value + length.value, dst.value, [inst]  # type: ignore
                )
                if len(intervals) == 0:
                    intervals.append(n_inter)
                else:
                    if not self._add_interval(intervals, n_inter, ok_self_overlap=True):
                        opt()
        self._zero_opt(bb, intervals)
