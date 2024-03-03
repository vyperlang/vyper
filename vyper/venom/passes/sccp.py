from dataclasses import dataclass
from enum import Enum
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


class SCCP(IRPass):
    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock, defs, uses) -> int:
        pass

    def _calculate_sccp(ctx: IRFunction, entry: IRBasicBlock, uses) -> map[IRVariable, LatticeItem]:
        ret: map[IRVariable, LatticeItem] = {}
        work_list: list[WorkListItem] = []

        dummy = IRBasicBlock(IRLabel("__dummy_start"), ctx)
        work_list.append(SSAWorkListItem(dummy, ctx.basic_blocks[0]))

        return ret
