from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.basicblock import IRInstruction, IRBasicBlock
from dataclasses import dataclass


@dataclass
class ValidCopy:
    src: int
    dst: int
    length: int

    place: IRInstruction
    others: list[IRInstruction]

class ValidCopiesAnalysis(IRAnalysis):
    valid_copies: dict[]

    def analyze(self, *args, **kwargs):
        return super().analyze(*args, **kwargs)

    def _handle_bb(self, bb: IRBasicBlock, load_op: str, copy_op: str):
        pass
