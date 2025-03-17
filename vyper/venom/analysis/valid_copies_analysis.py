from dataclasses import dataclass

from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IRVariable
from vyper.venom.effects import Effects


@dataclass
class ValidCopy:
    src: int
    dst: int
    length: int

    place: IRInstruction
    others: list[IRInstruction]


@dataclass
class BBValidCopies:
    bb: IRBasicBlock
    copies: list[ValidCopy]


class ValidCopiesAnalysis(IRAnalysis):
    valid_copies: dict[str, list[BBValidCopies]]

    _loads: dict[IRVariable, tuple[int, IRInstruction]]

    _load_to_copy = {"mload": "mcopy", "dload": "dloadbytes", "calldataload": "calldatacopy"}

    def analyze(self):
        self._loads = dict()
        self.valid_copies = dict()
        for load_op, copy_op in self._load_to_copy.items():
            self.valid_copies[load_op] = []
            for bb in self.function.get_basic_blocks():
                self._handle_bb(bb, load_op, copy_op)

    def _invalidate_loads(self, dst: int, length: int):
        for var, (src, _) in self._loads.copy().items():
            diff = abs(src - dst)
            if diff < max(length, 32):
                del self._loads[var]

    def _handle_bb(self, bb: IRBasicBlock, load_op: str, copy_op: str):
        res: list = []
        allow_ovelap = load_op == "mload"
        for inst in bb.instructions:
            if inst.opcode == load_op:
                src = inst.operands[0]
                if not isinstance(src, IRLiteral):
                    continue
                assert inst.output is not None
                self._loads[inst.output] = (src.value, inst)
            elif inst.opcode == "mstore":
                var, dst = inst.operands

                # could have trample anything
                if not isinstance(dst, IRLiteral):
                    self._loads.clear()
                    continue

                if not isinstance(var, IRVariable):
                    continue

                if not allow_ovelap:
                    self._invalidate_loads(dst.value, 32)

                # unknown memory (either invalidated or alredy non valid load or other instruction)
                if var not in self._loads:
                    continue

                src_ptr, load_inst = self._loads[var]
                copy = ValidCopy(src_ptr, dst.value, 32, inst, [load_inst])
                res.append(copy)
            elif inst.opcode == copy_op:
                if not all(isinstance(op, IRLiteral) for op in inst.operands):
                    continue

                length, src, dst = inst.operands
                if not allow_ovelap:
                    self._invalidate_loads(dst.value, length.value)

                # copy instruction can always create valid copy
                copy = ValidCopy(src.value, dst.value, length.value, inst, [])
                res.append(copy)
            elif _volatile_memory(inst):
                self._loads.clear()

        self.valid_copies[load_op].append(BBValidCopies(bb, res))


def _volatile_memory(inst):
    inst_effects = inst.get_read_effects() | inst.get_write_effects()
    return Effects.MEMORY in inst_effects or Effects.MSIZE in inst_effects
