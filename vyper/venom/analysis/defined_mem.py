from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis import CFGAnalysis
from vyper.venom.basicblock import IRInstruction, IRBasicBlock, IRVariable
from collections import deque

class DefinedMemoryVars(IRAnalysis):
    defined_at: dict[IRInstruction, set[IRVariable]]
    bb_defined: dict[IRBasicBlock, set[IRVariable]]

    allocas: set[IRVariable]

    def analyze(self):
        self.defined_at = dict()
        self.bb_defined = dict()
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        # assumes that all allocas are at entry
        self.allocas = set()
        for inst in self.function.entry.instructions:
            if inst.opcode == "alloca":
                self.allocas.add(inst.output)

        worklist = deque()
        worklist.append(self.function.entry)
        while len(worklist) > 0:
            bb = worklist.popleft()
            if self._process_bb(bb):
                for succ in self.cfg.cfg_out(bb):
                    worklist.append(succ)


    def _merge(self, bb: IRBasicBlock) -> set[IRVariable]:
        preds = list(self.cfg.cfg_in(bb))

        if len(preds) == 0:
            return set()

        preds_state = [self.bb_defined.get(pred, self.allocas) for pred in preds] 
        if len(preds_state) == 0:
            return set()

        result = preds_state[0].copy()

        for pred in preds_state[1:]:
            if pred is not None:
                result = result & pred

        return result
    
    def _process_bb(self, bb: IRBasicBlock) -> bool:
        curr = self._merge(bb)

        for inst in bb.instructions:
            if inst.opcode == "mstore":
                _, ptr = inst.operands
                if ptr in self.allocas:
                    assert isinstance(ptr, IRVariable)
                    curr.add(ptr)
            if inst.opcode == "mload":
                self.defined_at[inst] = curr.copy()
            if inst.opcode == "return":
                self.defined_at[inst] = curr.copy()
        
        if bb not in self.bb_defined or self.bb_defined[bb] != curr:
            self.bb_defined[bb] = curr
            return True

        return False
