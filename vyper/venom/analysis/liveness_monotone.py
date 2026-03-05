from vyper.venom.analysis.monotone_base import LatticeBase, MonotoneAnalysis, Direction
from vyper.venom.basicblock import IRVariable, IRInstruction
from dataclasses import dataclass

@dataclass
class LivenessLattice(LatticeBase):
    data: set[IRVariable]

class LivenessMonotoneAnalysis(MonotoneAnalysis[LivenessLattice]):
    def _direction(self) -> Direction:
        return Direction.Backwards

    def _join(self, a: LivenessLattice, b: LivenessLattice):
        return LivenessLattice(a.data.union(b.data))

    def _bottom(self):
        return LivenessLattice(set())

    def _transfer_function(self, inst: IRInstruction, input_lattice: LivenessLattice) -> LivenessLattice:
        result : LivenessLattice = input_lattice.copy()
        for output in inst.get_outputs():
            result.data.remove(output)
        
        for op in inst.operands:
            if isinstance(op, IRVariable):
                result.data.add(op)

        return result
