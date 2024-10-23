from vyper.venom.basicblock import IRInstruction, IRLiteral
from vyper.venom.passes.base_pass import IRPass


class AllocaElimination(IRPass):
    """
    This pass eliminates alloca instructions by allocating memory for them
    """

    def run_pass(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "alloca":
                    self._process_alloca(inst)

    def _process_alloca(self, inst: IRInstruction):
        offset, _size = inst.operands
        address = inst.parent.parent._mem_allocator.allocate(_size.value)
        inst.opcode = "store"
        inst.operands = [IRLiteral(address)]
        # print(f"Allocated address {address} for alloca {_size.value}")
