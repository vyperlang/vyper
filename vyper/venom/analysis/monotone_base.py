from __future__ import annotations
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis import CFGAnalysis
from vyper.venom.basicblock import IRInstruction, IRBasicBlock
from collections import deque
from enum import Enum
from typing import TypeVar, Type, Generic

class Direction(Enum):
    Forward = 1
    Backwards = 2

class LatticeBase:
    def copy(self) -> Lattice:
        pass


Lattice = TypeVar("Lattice", bound=LatticeBase)
class MonotoneAnalysis(Generic[Lattice], IRAnalysis):
    def analyze(self):
        worklist = deque()
        self.inst_lattice: dict[IRInstruction, Lattice] = {}
        self.bb_output: dict[IRBasicBlock, Lattice]= {}
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
    
        for bb in self.function.get_basic_blocks():
            bottom: Lattice = self._bottom()
            self.bb_output[bb] = bottom

        while worklist:
            bb = worklist.popleft()

            lattice = self._compute_join(bb)

            if self._process_bb(bb, lattice):
                if self._direction() == Direction.Forward:
                    for successor in self.cfg.cfg_out(bb):
                        worklist.append(successor)
                else:
                    for predecessor in self.cfg.cfg_in(bb):
                        worklist.append(predecessor)


    def _process_bb(self, bb: IRBasicBlock, current_lattice: Lattice) -> bool:
        instructions = bb.instructions
        if self._direction() == Direction.Backwards:
            instructions = reversed(instructions)
        
        for inst in instructions:
            self.inst_lattice[inst] = current_lattice.copy()
            
            current_lattice = self._transfer_function(inst, current_lattice)

        if bb not in self.bb_output or self.bb_output[bb] != current_lattice:
            self.bb_output[bb] = current_lattice
            return True

        return False

    def _direction(self) -> Direction:
        raise NotImplementedError()

    def _compute_join(self, bb: IRBasicBlock) -> Lattice:
        input_lattices = []
        if self._direction() == Direction.Forward:
            predecessors = self.cfg.cfg_in(bb)
        else:
            predecessors = self.cfg.cfg_out(bb)
            
        for pred in predecessors:
            input_lattices.append(self.bb_output[pred])
        
        if not input_lattices:
            return self._bottom()
        
        result = input_lattices[0]
        for lattice in input_lattices[1:]:
            result = self._join(result, lattice)
        return result

    def _bottom(self) -> Lattice:
        raise NotImplementedError()

    def _join(self, a: Lattice, b: Lattice) -> Lattice:
        """Join operation for the lattice"""
        raise NotImplementedError()
    

    def _transfer_function(self, inst: IRInstruction, input_lattice: Lattice) -> Lattice:
        """Transfer function for an instruction"""
        raise NotImplementedError()
