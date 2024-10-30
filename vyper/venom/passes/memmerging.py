from vyper.venom.passes.base_pass import IRPass
from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.basicblock import IRLiteral, IRVariable
from vyper.venom.basicblock import IRInstruction
from dataclasses import dataclass
from vyper.venom.analysis import DFGAnalysis
from vyper.venom.effects import Effects
from bisect import bisect_left

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
    
    def overlap(self) -> bool:
        dst_end = self.dst_start + self.length
        return (
            self.src_start <= self.dst_start <= self.src_end 
            or self.src_start <= dst_end <= self.src_end 
            or self.dst_start <= self.src_start <= dst_end
            or self.dst_start <= self.src_end <= dst_end
        )

    def add(self, src, dst, length, insts: list[IRInstruction]) -> bool:
        if src != self.src_end:
            return False
        if dst != self.dst_end:
            return False

        n_inter = _Interval(self.src_start, self.src_end + length, self.dst_start, [])
        if n_inter.overlap():
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

    
class MemMergePass(IRPass):
    dfg: DFGAnalysis

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis) # type: ignore

        for bb in self.function.get_basic_blocks():
            self._handle_bb(bb)

    def _opt_intervals(self, bb: IRBasicBlock, intervals: list[_Interval]):
        for inter in intervals:
            inter.insts[0].output = None
            inter.insts[0].opcode = "mcopy"
            inter.insts[0].operands = [IRLiteral(inter.length), IRLiteral(inter.src_start), IRLiteral(inter.dst_start)]
            for inst in inter.insts[1:]:
                bb.remove_instruction(inst)

        intervals.clear()


    def _handle_bb(self, bb: IRBasicBlock):
        loads: dict[IRVariable, int] = dict()
        intervals: list[_Interval] = []

        for inst in bb.instructions:
            if inst.opcode == "mload":
                src = inst.operands[0]
                if not isinstance(src, IRLiteral):
                    continue
                uses = self.dfg.get_uses(inst.output) # type: ignore
                if len(uses) != 1:
                    continue
                if uses.first().opcode != "mstore":
                    continue
                assert isinstance(inst.output, IRVariable)
                loads[inst.output] = src.value
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
                if not var in loads:
                    self._opt_intervals(bb, intervals)
                    loads.clear()
                    continue
                src = loads[var]
                n_inter = _Interval(src, src + 32, dst.value, [self.dfg.get_producing_instruction(var), inst]) # type: ignore
                if n_inter in intervals:
                    self._opt_intervals(bb, intervals);
                    loads.clear()
                if len(intervals) == 0:
                    intervals.append(n_inter)
            elif Effects.MEMORY in inst.get_write_effects():
                self._opt_intervals(bb, intervals)
                loads.clear()
        self._opt_intervals(bb, intervals)
