from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.context import IRFunction
from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.basicblock import IRInstruction
from vyper.venom.basicblock import IRLiteral
from vyper.venom.basicblock import IRVariable
from vyper.venom.basicblock import IROperand
from vyper.venom.basicblock import BB_TERMINATORS
from vyper.utils import OrderedSet
from dataclasses import dataclass
from collections import deque

@dataclass
class _Expression:
    first_inst : IRInstruction
    opcode: str
    operands : list[IROperand]

    def __eq__(self, other):
        if not isinstance(other, _Expression):
            return False
        #return self.opcode == other.opcode and self.operands == other.operands and fi
        return self.first_inst == other.first_inst
    
    def __hash__(self) -> int:
        res : int = hash(self.opcode)
        for op in self.operands:
            res ^= hash(op)
        return res

    def __repr__(self) -> str:
        if self.opcode == "store":
            assert len(self.operands) == 1, "wrong store"
            return repr(self.operands[0])
        res = self.opcode + " [ "
        for op in self.operands:
            res += repr(op) + " "
        res += "]"
        return res

    def contains_expr(self, expr : "_Expression") -> bool:
        for op in self.operands:
            if op == expr:
                return True
            if isinstance(op, _Expression) and op.contains_expr(expr):
                return True
        return False

class _BBLattice:
    data : dict[IRInstruction, OrderedSet[_Expression]]
    out : OrderedSet[_Expression]
    in_cache: OrderedSet[_Expression] | None

    def __init__(self, bb : IRBasicBlock):
        self.data = dict()
        self.out = OrderedSet()
        self.in_cache = None
        for inst in bb.instructions:
            self.data[inst] = OrderedSet()

UNINTRESTING_OPCODES = [
    "store",
    "param",
    "offset",
    "phi",
    "nop",
    "assert",
]

_ALL = ("storage", "transient", "memory", "immutables", "balance", "returndata")

writes = {
    "sstore": ("storage"),
    "tstore": ("transient"),
    "mstore": ("memory"),
    "istore": ("immutables"),
    "call": _ALL,
    "delegatecall": _ALL,
    "staticcall": ("memory"),
    "create": _ALL,
    "create2": _ALL,
    "invoke": _ALL,  # could be smarter, look up the effects of the invoked function
    "dloadbytes": ("memory"),
    "returndatacopy": ("memory"),
    "calldatacopy": ("memory"),
    "codecopy": ("memory"),
    "extcodecopy": ("memory"),
    "mcopy": ("memory"),
}
reads = {
    "sload": ("storage"),
    "tload": ("transient"),
    "iload": ("immutables"),
    "mload": ("memory"),
    "mcopy": ("memory"),
    "call": _ALL,
    "delegatecall": _ALL,
    "staticcall": _ALL,
    "returndatasize": ("returndata"),
    "returndatacopy": ("returndata"),
    "balance": ("balance"),
    "selfbalance": ("balance"),
    "log": ("memory"),
    "revert": ("memory"),
    "return": ("memory"),
    "sha3": ("memory"),
}


class _FunctionLattice:
    data : dict[IRBasicBlock, _BBLattice]

    def __init__(self, function : IRFunction):
        self.data = dict()
        for bb in function.get_basic_blocks():
            self.data[bb] = _BBLattice(bb)

class AvailableExpressionAnalysis(IRAnalysis):
    expressions : OrderedSet[_Expression] = OrderedSet()
    inst_to_expr: dict[IRInstruction, _Expression] = dict()
    dfg: DFGAnalysis
    lattice : _FunctionLattice

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        assert isinstance(dfg, DFGAnalysis)
        self.dfg = dfg

        self.lattice = _FunctionLattice(function)

    def analyze(self, *args, **kwargs):
        worklist = deque()
        worklist.append(self.function.entry)
        while len(worklist) > 0:
            bb : IRBasicBlock = worklist.popleft()
            changed = self._handle_bb(bb)

            if changed:
                for out in bb.cfg_out:
                    if out not in worklist:
                        worklist.append(out)
    
    def _handle_bb(self, bb : IRBasicBlock) -> bool:
        available_expr : OrderedSet[_Expression] = OrderedSet()
        if len(bb.cfg_in) > 0:
            available_expr = OrderedSet.intersection(*(self.lattice.data[in_bb].out for in_bb in bb.cfg_in))
        
        bb_lat = self.lattice.data[bb]
        if bb_lat.in_cache is not None and available_expr == bb_lat.in_cache:
            return False
        bb_lat.in_cache = available_expr
        change = False
        for inst in bb.instructions:
            if (inst.opcode in UNINTRESTING_OPCODES 
                or inst.opcode in BB_TERMINATORS 
                or inst.output == None):
                continue
            inst_expr = self.get_expression(inst, available_expr)
            if available_expr != bb_lat.data[inst]:
                bb_lat.data[inst] = available_expr.copy()
                change |= True

            write_effects = writes.get(inst_expr.opcode, ())
            for expr in available_expr.copy():
                if expr.contains_expr(inst_expr):
                    available_expr.remove(expr)
                read_effects = reads.get(expr.opcode, ())
                if any(eff in write_effects for eff in read_effects):
                    available_expr.remove(expr)

            available_expr.add(inst_expr)

        if available_expr != bb_lat.out:
            bb_lat.out = available_expr.copy()
            change |= True
        
        return change

    def get_expression(self, inst: IRInstruction, available_exprs : OrderedSet[_Expression] | None = None) -> _Expression:
        if available_exprs is None:
            available_exprs = self.lattice.data[inst.parent].data[inst]
        operands: list[IROperand] = inst.operands.copy()
        expr = _Expression(inst, inst.opcode, operands)
        #if expr in available_exprs:
        for e in available_exprs:
            if e.opcode == expr.opcode and e.operands == expr.operands:
                return e
        
        return expr

    def get_available(self, inst : IRInstruction) -> OrderedSet[_Expression]:
        return self.lattice.data[inst.parent].data[inst]

