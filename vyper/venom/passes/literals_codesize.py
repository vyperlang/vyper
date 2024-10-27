from vyper.utils import evm_not
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

            val = op.value

            if val == (2**256 - 1):
                inst.opcode = "not"
                op.value = 0
                continue

            # TODO: fuse these two rules?

            # transform things like 0xffff...01 to (not 0xfe)
            binz = bin(val)[2:]
            if (ix := binz.find("0")) > 8:  # `not` is 1 byte
                inst.opcode = "not"
                op.value = evm_not(val)
                continue

            if (ix := len(binz) - binz.rfind("1")) > 24:  # shl is 3 bytes
                ix -= 1
                inst.opcode = "shl"
                # sanity check
                assert (val >> ix) << ix == val, val
                assert (val >> ix) & 1 == 1

                inst.operands = [IRLiteral(val >> ix), IRLiteral(ix)]
                continue
