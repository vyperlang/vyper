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
    operands : list["_Expression | IROperand"]

    def __eq__(self, other):
        if not isinstance(other, _Expression):
            return False
        return self.opcode == other.opcode and self.operands == other.operands
    
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
            #if self.opcode != "phi":
                #assert not isinstance(op, IRVariable)
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
        
        if bb.label.name == "5_if_exit":
            pass
            print(bb.label)
            print(type(available_expr))
            print(type(available_expr._data))
            print(len(available_expr))
            print(available_expr)

        bb_lat = self.lattice.data[bb]
        if bb_lat.in_cache is not None and available_expr == bb_lat.in_cache:
            return False
        bb_lat.in_cache = available_expr
        change = False
        for inst in bb.instructions:
            if bb.label.name == "5_if_exit":
                print(inst)
            if "call" in inst.opcode:
                for expr in available_expr.copy():
                    if "returndata" in expr.opcode:
                        available_expr.remove(expr)
                continue
            if (inst.opcode in UNINTRESTING_OPCODES 
                or inst.opcode in BB_TERMINATORS 
                or inst.output == None):
                continue
            inst_expr = self.get_expression(inst)
            if inst.output is not None and inst.output.name == "%25":
                print(available_expr)
            if available_expr != bb_lat.data[inst]:
                bb_lat.data[inst] = available_expr.copy()
                change |= True
            for expr in available_expr.copy():
                if expr.contains_expr(inst_expr):
                    available_expr.remove(expr)
            available_expr.add(inst_expr)

        if available_expr != bb_lat.out:
            bb_lat.out = available_expr.copy()
            change |= True
        
        #if change:
            #print(bb.label)
        return change

    def _get_operand(self, op : IROperand) -> _Expression | IROperand:
        if False and isinstance(op, IRVariable):
            inst = self.dfg.get_producing_instruction(op)
            assert inst is not None
            return self.get_expression(inst)
        return op

    def get_expression(self, inst: IRInstruction) -> _Expression:
        if inst in self.inst_to_expr.keys():
            return self.inst_to_expr[inst]
        if inst.opcode == "phi":
            operands: list[_Expression | IROperand] = inst.operands.copy()
        else:
            operands = [self._get_operand(op) for op in inst.operands]
        expr = _Expression(inst, inst.opcode, operands)
        for e in self.expressions:
            if e == expr:
                self.inst_to_expr[inst] = e
                #print("yo", e)
                return e
        
        self.expressions.add(expr)
        self.inst_to_expr[inst] = expr
        return expr

    def get_available(self, inst : IRInstruction) -> OrderedSet[_Expression]:
        return self.lattice.data[inst.parent].data[inst]

