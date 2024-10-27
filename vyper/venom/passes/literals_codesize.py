from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IRVariable, IROperand
from vyper.venom.passes.base_pass import IRPass

class ReduceLiteralsCodesize(IRPass):
    def run_pass(self):
        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_bb(self, bb):
        i = 0
        while i < len(bb.instructions):
            inst = bb.instructions[i]
            i += 1
            if inst.opcode != "store":
                continue

            op = inst.operands[0]
            if not isinstance(op, IRLiteral):
                continue

            val = op.value

            if val == (2**256 - 1):
                inst.opcode = "not"
                inst.value = 0
                continue

            # transform things like 0xffff...01 to (not 0xfe)
            binz = bin(val)[2:]
            if (ix := binz.find("0")) > 8:  # `not` is 1 byte
                inst.opcode = "not"
                op.value = (2**256) - val
                continue

            if (ix := len(binz) - binz.rfind("1")) > 24:  # shl is 3 bytes
                ix -= 1
                inst.opcode = "shl"
                assert (val>>ix) << ix == val, val
                inst.operands = [IRLiteral(val>>ix), IRLiteral(ix)]
                continue
