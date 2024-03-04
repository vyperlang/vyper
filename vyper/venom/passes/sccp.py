from dataclasses import dataclass
from enum import Enum
from functools import reduce
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
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
type Lattice = map[IRVariable, LatticeItem]


def _meet(x: LatticeItem, y: LatticeItem) -> LatticeItem:
    if x == LatticeEnum.TOP:
        return y
    if y == LatticeEnum.TOP or x == y:
        return x
    return LatticeEnum.BOTTOM


class SCCP(IRPass):
    uses: map[IRVariable, IRBasicBlock]
    defs: map[IRVariable, IRInstruction]
    lattice: Lattice
    work_list: list[WorkListItem]

    def __init__(self, uses: map[IRVariable, IRBasicBlock]):
        self.uses = uses
        self.lattice = {}
        self.work_list: list[WorkListItem] = []

    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock) -> int:
        self._calculate_sccp(ctx, entry)

    def _calculate_sccp(self, ctx: IRFunction, entry: IRBasicBlock) -> map[IRVariable, LatticeItem]:

        dummy = IRBasicBlock(IRLabel("__dummy_start"), ctx)
        self.work_list.append(SSAWorkListItem(dummy, ctx.basic_blocks[0]))

        for v in self.uses.keys():
            self.lattice[v] = LatticeEnum.TOP

        while len(self.work_list) > 0:
            workItem = self.work_list.pop()
            if isinstance(workItem, FlowWorkItem):
                if workItem.start in workItem.end.cfg_in_exec:
                    continue
                workItem.end.cfg_in_exec.add(workItem.start)

                for inst in workItem.end.instructions:
                    if inst.opcode == "phi":
                        self._visitPhi(inst)
            else:
                pass

    def _visitPhi(self, inst: IRInstruction):
        assert inst.opcode == "phi", "Can't visit non phi instruction"
        labels = inst.get_label_operands()
        bb = inst.parent
        assert bb is not None
        vars = []
        for bb, var in inst.phi_operands:
            if bb not in bb.cfg_in_exec:
                continue
            vars.append(self.lattice[var])
        value = reduce(var, _meet, LatticeEnum.TOP)
        if value != self.lattice(inst.output):
            self.lattice[inst.output] = value
            for use in self.uses[inst.output]:
                self.worklist.add(use)
