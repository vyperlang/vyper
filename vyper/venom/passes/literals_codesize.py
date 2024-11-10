from vyper.utils import SizeLimits, evm_not
from vyper.venom.basicblock import IRLiteral
from vyper.venom.passes.base_pass import IRPass


class ReduceLiteralsCodesize(IRPass):
    def run_pass(self):
        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

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

            val = op.value % (2**256)

            # transform things like 0xffff...01 to (not 0xfe)
            if len(hex(val)) // 2 - len(hex(evm_not(val))) // 2 > 0:
                inst.opcode = "not"
                op.value = evm_not(val)
                continue

            # transform things like 0x123400....000 to 0x1234 << ...
            binz = bin(val)[2:]
            if (ix := len(binz) - binz.rfind("1")) > 24:  # shl is 3 bytes
                ix -= 1
                inst.opcode = "shl"
                # sanity check
                assert (val >> ix) << ix == val, val
                assert (val >> ix) & 1 == 1, val

                inst.operands = [IRLiteral(val >> ix), IRLiteral(ix)]
                continue
