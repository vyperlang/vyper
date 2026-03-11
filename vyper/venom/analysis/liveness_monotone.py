from dataclasses import dataclass

from vyper.utils import OrderedSet
from vyper.venom.analysis.monotone_base import Direction, LatticeBase, MonotoneAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable


@dataclass
class LivenessLattice(LatticeBase):
    data: OrderedSet[IRVariable]

    def copy(self):
        return LivenessLattice(self.data.copy())


class LivenessMonotoneAnalysis(MonotoneAnalysis[LivenessLattice]):
    def _direction(self) -> Direction:
        return Direction.Backwards

    def _join(self, a: LivenessLattice, b: LivenessLattice):
        tmp: OrderedSet = a.data.union(b.data)
        return LivenessLattice(tmp)

    def _bottom(self):
        return LivenessLattice(OrderedSet())

    def _transfer_function(
        self, inst: IRInstruction, input_lattice: LivenessLattice
    ) -> LivenessLattice:
        result: LivenessLattice = input_lattice.copy()
        for output in inst.get_outputs():
            if output in result.data:
                result.data.remove(output)

        for op in inst.operands:
            if isinstance(op, IRVariable):
                result.data.add(op)

        return result

    def live_vars_at(self, inst: IRInstruction) -> OrderedSet[IRVariable]:
        """
        Get the variables that are live at (right before) a given instruction
        """
        return self.inst_lattice[inst].data
