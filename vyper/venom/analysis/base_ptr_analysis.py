from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.memory_location import MemoryLocation
from vyper.venom.basicblock import IRVariable, IRAbstractMemLoc, IRInstruction, IRLiteral

class BasePtrAnalysis(IRAnalysis):
    var_to_mem: dict[IRVariable, MemoryLocation]

    def analyze(self):
        self.var_to_mem = dict()

        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                self._handle_inst(inst)

    def _handle_inst(self, inst: IRInstruction):
        if inst.output is None:
            return

        opcode = inst.opcode
        if opcode in ("alloca", "calloca", "palloca"):
            pass
        elif opcode == "gep":
            assert isinstance(inst.operands[0], IRVariable)
            offset = None
            if isinstance(inst.operands[1], IRLiteral):
                offset = inst.operands[1].value
            self.var_to_mem[inst.output] = self.var_to_mem[inst.operands[0]].offset_by(offset)
        elif opcode == "phi":
            pass
        elif opcode == "assign" and isinstance(inst.operands[0], IRVariable):
            self.var_to_mem[inst.output] = self.var_to_mem[inst.operands[0]]

