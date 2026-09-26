from dataclasses import dataclass

from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis.monotone_base import Direction, LatticeBase, MonotoneAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable


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

    def _edge_transfer(
        self, source: IRBasicBlock, target: IRBasicBlock, input_lattice: LivenessLattice
    ) -> LivenessLattice:
        """
        Same as LivenessAnalysis.input_vars_from.
        """
        phis: list[IRInstruction] = []
        for inst in target.instructions:
            if inst.opcode == "phi":
                if source.label not in inst.operands:
                    raise CompilerPanic(f"unreachable: {inst} from {source.label}")
                phis.append(inst)
            else:
                break

        if len(phis) == 0:
            return input_lattice

        # Map every phi operand (from all sources) to its phi index,
        # and record the matching operand from `source` for each phi.
        operand_to_phi_idx: dict[IRVariable, int] = {}
        phi_matching: dict[int, IRVariable] = {}
        for i, phi in enumerate(phis):
            for label, var in phi.phi_operands:
                assert isinstance(var, IRVariable)
                operand_to_phi_idx[var] = i
                if label == source.label:
                    phi_matching[i] = var

        result: OrderedSet[IRVariable] = OrderedSet()
        placed: set[int] = set()

        for var in input_lattice.data:
            phi_idx = operand_to_phi_idx.get(var)
            if phi_idx is not None:
                if phi_idx not in placed:
                    placed.add(phi_idx)
                    result.add(phi_matching[phi_idx])
                # else: skip subsequent operands of same phi
            else:
                result.add(var)

        return LivenessLattice(result)

    def live_vars_at(self, inst: IRInstruction) -> OrderedSet[IRVariable]:
        """
        Get the variables that are live at (right before) a given instruction
        """
        return self.inst_lattice[inst].data
