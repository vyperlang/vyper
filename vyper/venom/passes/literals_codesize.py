from vyper.utils import evm_not
from vyper.venom.basicblock import IRInstruction, IRLiteral
from vyper.venom.passes.base_pass import IRPass

# not takes 1 byte1, so it makes sense to use it when we can save at least
# 1 byte
NOT_THRESHOLD = 1

# shl takes 3 bytes, so it makes sense to use it when we can save at least
# 3 bytes
SHL_THRESHOLD = 3


class ReduceLiteralsCodesize(IRPass):
    def run_pass(self):
        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

    def _process_bb(self, bb):
        for inst in list(bb.instructions):
            if inst.opcode != "assign":
                continue

            (op,) = inst.operands
            if not isinstance(op, IRLiteral):
                continue

            val = op.value % (2**256)

            # calculate amount of bits saved by not optimization
            not_benefit = ((len(hex(val)) // 2 - len(hex(evm_not(val))) // 2) - NOT_THRESHOLD) * 8

            # calculate amount of bits saved by shl optimization
            binz = bin(val)[2:]
            ix = len(binz) - binz.rfind("1")
            shl_benefit = ix - SHL_THRESHOLD * 8

            if not_benefit <= 0 and shl_benefit <= 0:
                # no optimization can be done here
                continue

            if not_benefit >= shl_benefit:
                assert not_benefit > 0  # implied by previous conditions
                # transform things like 0xffff...01 to (not 0xfe)
                inst.opcode = "not"
                inst.operands = [IRLiteral(evm_not(val))]
                continue
            else:
                assert shl_benefit > 0  # implied by previous conditions
                # transform things like 0x123400....000 to 0x1234 << ...
                ix -= 1
                # sanity check
                assert (val >> ix) << ix == val, val
                assert (val >> ix) & 1 == 1, val

                mantissa = val >> ix
                # `shl k, k` repeats one literal. DFT and the assembler need
                # distinct operands, so split only that case into two assigns.
                # Other literals stay inline; a later SingleUseExpansion would
                # reschedule them and change codesize.
                if mantissa == ix:
                    idx = bb.instructions.index(inst)
                    left = bb.parent.get_next_variable()
                    right = bb.parent.get_next_variable()
                    bb.insert_instruction(
                        IRInstruction("assign", [IRLiteral(mantissa)], [left]), idx
                    )
                    bb.insert_instruction(
                        IRInstruction("assign", [IRLiteral(ix)], [right]), idx + 1
                    )
                    inst.opcode = "shl"
                    inst.operands = [left, right]
                    continue

                inst.opcode = "shl"
                inst.operands = [IRLiteral(mantissa), IRLiteral(ix)]
                continue
