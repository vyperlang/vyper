from vyper.venom.analysis.analysis import IRAnalysis, IRAnalysesCache
from vyper.venom.analysis import CFGAnalysis
from vyper.venom.basicblock import IROperand, IRInstruction, IRBasicBlock, IRVariable, IRLiteral
from vyper.venom.effects import Effects
from collections import deque

Lattice = dict[IROperand, set[IROperand]]

def _conflict(store_opcode: str, k1: IRLiteral, k2: IRLiteral):
    ptr1, ptr2 = k1.value, k2.value
    # hardcode the size of store opcodes for now. maybe refactor to use
    # vyper.evm.address_space
    if store_opcode == "mstore":
        return abs(ptr1 - ptr2) < 32
    assert store_opcode in ("sstore", "tstore"), "unhandled store opcode"
    return abs(ptr1 - ptr2) < 1

class LoadAnalysis(IRAnalysis):
    InstToLattice = dict[IRInstruction, Lattice]
    lattice: dict[Effects|str, InstToLattice]
    cfg: CFGAnalysis

    def analyze(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.lattice = dict()

        self._analyze_type(Effects.MEMORY, "mload", "mstore")
        self._analyze_type(Effects.TRANSIENT, "tload", "tstore")
        self._analyze_type(Effects.STORAGE, "sload", "sstore")
        self._analyze_type("dload", "dload", None)
        self._analyze_type("calldataload", "calldataload", None)

    def _analyze_type(self, eff: Effects|str, load_opcode: str, store_opcode: str|None):
        self.inst_to_lattice: LoadAnalysis.InstToLattice = dict()
        self.bb_to_lattice: dict[IRBasicBlock, Lattice] = dict()

        worklist = deque(self.cfg.dfs_pre_walk)

        while len(worklist) > 0:
            bb = worklist.popleft()
            change = self._handle_bb(eff, load_opcode, store_opcode, bb)

            if change:
                for succ in self.cfg.cfg_out(bb):
                    worklist.append(succ)

        self.lattice[eff] = self.inst_to_lattice
    
    def _merge(self, bb: IRBasicBlock) -> Lattice:
        preds = list(self.cfg.cfg_in(bb))
        if len(preds) == 0:
            return dict()
        res = self.bb_to_lattice.get(preds[0], dict())

        for pred in preds[1:]:
            other = self.bb_to_lattice.get(pred, dict())
            common_keys = other.keys() & res.keys()
            tmp = res.copy()
            res = dict()
            for key in common_keys:
                res[key] = tmp[key] | other[key]
        
        return res

    def _handle_bb(self, eff: Effects|str, load_opcode: str, store_opcode: str|None, bb: IRBasicBlock):
        # this should join later
        lattice = self._merge(bb) 

        for inst in bb.instructions:
            if inst.opcode == load_opcode:
                self.inst_to_lattice[inst] = lattice.copy()
                ptr = inst.operands[0]
                assert inst.output is not None
                lattice[ptr] = set([inst.output])
            elif inst.opcode == store_opcode:
                self.inst_to_lattice[inst] = lattice.copy()
                # mstore [val, ptr]
                val, ptr = inst.operands
                if isinstance(ptr, IRVariable):
                    lattice.clear()
                    lattice[ptr] = set([val])
                    continue

                assert isinstance(ptr, IRLiteral)

                # kick out any conflicts
                for existing_key in lattice.copy().keys():
                    if not isinstance(existing_key, IRLiteral):
                        # a variable in the lattice. assign this ptr in the lattice
                        # and flush everything else.
                        lattice.clear()
                        lattice[ptr] = set([val])
                        break

                    if store_opcode is not None:
                        if _conflict(store_opcode, ptr, existing_key):
                            del lattice[existing_key]

                lattice[ptr] = set([val])
            elif isinstance(eff, Effects) and eff in inst.get_write_effects():
                lattice.clear()
