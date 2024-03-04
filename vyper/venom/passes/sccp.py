from dataclasses import dataclass
from enum import Enum
from functools import reduce
from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet, SizeLimits
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class LatticeEnum(Enum):
    TOP = 1
    BOTTOM = 2


@dataclass
class SSAWorkListItem:
    inst: IRInstruction
    basic_block: IRBasicBlock


@dataclass
class FlowWorkItem:
    start: IRBasicBlock
    end: IRBasicBlock


type WorkListItem = FlowWorkItem | SSAWorkListItem

type LatticeItem = LatticeEnum | IRLiteral
type Lattice = dict[IRVariable, LatticeItem]


class SCCP(IRPass):
    ctx: IRFunction
    dom: DominatorTree
    uses: dict[IRVariable, IRBasicBlock]
    defs: dict[IRVariable, IRInstruction]
    lattice: Lattice
    work_list: list[WorkListItem]

    def __init__(self, dom: DominatorTree):
        self.dom = dom
        self.lattice = {}
        self.work_list: list[WorkListItem] = []

    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock) -> int:
        self.ctx = ctx
        self._compute_uses(self.dom)
        self._calculate_sccp(entry)

    def _calculate_sccp(self, entry: IRBasicBlock) -> dict[IRVariable, LatticeItem]:

        dummy = IRBasicBlock(IRLabel("__dummy_start"), self.ctx)
        self.work_list.append(FlowWorkItem(dummy, self.ctx.basic_blocks[0]))

        for v in self.uses.keys():
            self.lattice[v] = LatticeEnum.TOP

        while len(self.work_list) > 0:
            workItem = self.work_list.pop()
            if isinstance(workItem, FlowWorkItem):
                start = workItem.start
                end = workItem.end
                if start in end.cfg_in_exec:
                    continue
                end.cfg_in_exec.add(start)

                for inst in end.instructions:
                    if inst.opcode == "phi":
                        self._visitPhi(inst)

                if len(end.cfg_in_exec) == 1:
                    for inst in end.instructions:
                        self._visitExpr(inst)

                if len(end.cfg_out) == 1:
                    self.work_list.append(FlowWorkItem(end, end.cfg_out.first()))
            elif isinstance(workItem, SSAWorkListItem):
                if workItem.inst.opcode == "phi":
                    self._visitPhi(workItem.inst)
                else:
                    self._visitExpr(workItem.inst)
                pass

    def _visitPhi(self, inst: IRInstruction):
        assert inst.opcode == "phi", "Can't visit non phi instruction"
        vars = []
        for bb, var in inst.phi_operands:
            if bb not in inst.parent.cfg_in_exec:
                continue
            vars.append(self.lattice[var])
        value = reduce(_meet, vars, LatticeEnum.TOP)
        if value != self.lattice[inst.output]:
            self.lattice[inst.output] = value
            for use in self.uses[inst.output]:
                self.work_list.append(use)

    def _visitExpr(self, inst: IRInstruction):
        opcode = inst.opcode
        if opcode in ["add", "sub"]:
            self._eval(inst)
        elif opcode == "push":
            self.lattice[inst.output] = inst.operands[0]
            self._add_ssa_work_items(inst)
        elif opcode == "jmp":
            target = self.ctx.get_basic_block(inst.operands[0].value)
            self.work_list.append(FlowWorkItem(inst.parent, target))
        elif opcode == "jnz":
            lat = self.lattice[inst.operands[2]]
            if _meet(lat, 0) == LatticeEnum.BOTTOM:
                target = self.ctx.get_basic_block(inst.operands[1].value)
                self.work_list.append(FlowWorkItem(inst.parent, target))
            if _meet(lat, 1) == LatticeEnum.BOTTOM:
                target = self.ctx.get_basic_block(inst.operands[0].value)
                self.work_list.append(FlowWorkItem(inst.parent, target))
        elif opcode == "param":
            self.lattice[inst.output] = LatticeEnum.BOTTOM
            self._add_ssa_work_items(inst)

    def _eval(self, inst) -> LatticeItem:
        opcode = inst.opcode

        ops = []
        for op in inst.get_non_label_operands():
            if isinstance(op, IRVariable):
                ops.append(self.lattice[op])
            else:
                ops.append(op)

        if LatticeEnum.BOTTOM in ops:
            self.lattice[inst.output] = LatticeEnum.BOTTOM
            return LatticeEnum.BOTTOM

        ret = None
        if opcode == "add":
            ret = IRLiteral((ops[0].value + ops[1].value) & SizeLimits.MAX_UINT256)
        elif opcode == "sub":
            ret = IRLiteral((ops[0].value - ops[1].value) & SizeLimits.MAX_UINT256)
        elif len(ops) > 0:
            ret = ops[0]
        else:
            raise CompilerPanic("Bad constant evaluation")

        self.lattice[inst.output] = ret
        self._add_ssa_work_items(inst)
        return ret

    def _add_ssa_work_items(self, inst: IRInstruction):
        if inst.output not in self.uses:
            self.uses[inst.output] = []
        for use in self.uses[inst.output]:
            self.work_list.append(use)

    def _compute_uses(self, dom: DominatorTree):
        self.uses = {}
        for bb in dom.dfs:
            for var, insts in bb.get_uses().items():
                if var not in self.uses:
                    self.uses[var] = OrderedSet()
                self.uses[var].update(insts)


def _meet(x: LatticeItem, y: LatticeItem) -> LatticeItem:
    if x == LatticeEnum.TOP:
        return y
    if y == LatticeEnum.TOP or x == y:
        return x
    return LatticeEnum.BOTTOM
