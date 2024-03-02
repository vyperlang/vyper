from dataclasses import dataclass
from enum import Enum
from vyper.venom.basicblock import IRBasicBlock, IRLiteral, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class LatticeEnum(Enum):
    TOP = 1
    BOTTOM = 2


type LatticeItem = LatticeEnum | IRLiteral


class SCCP(IRPass):
    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock, defs, uses) -> int:
        pass

    def _calculate_sccp(ctx: IRFunction, entry: IRBasicBlock, uses) -> map[IRVariable, LatticeItem]:
        pass
