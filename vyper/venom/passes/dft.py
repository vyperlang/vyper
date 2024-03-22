from vyper.utils import OrderedSet
from vyper.venom.analysis import DFG
from vyper.venom.basicblock import BB_TERMINATORS, IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class DFTPass(IRPass):
    def _process_instruction_r(self, bb: IRBasicBlock, inst: IRInstruction, offset: int = 0):
        for op in inst.get_outputs():
            assert isinstance(op, IRVariable), f"expected variable, got {op}"
            uses = self.dfg.get_uses(op)

            for uses_this in uses:
                if uses_this.parent != inst.parent or uses_this.fence_id != inst.fence_id:
                    # don't reorder across basic block or fence boundaries
                    continue
                self._process_instruction_r(
                    bb, uses_this, 1000 if uses_this.opcode in BB_TERMINATORS else offset
                )

        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)

        if inst.opcode == "phi":
            # phi instructions stay at the beginning of the basic block
            # and no input processing is needed
            # bb.instructions.append(inst)
            self.inst_order_num += 1
            self.inst_order[inst] = self.inst_order_num + offset
            return

        for op in inst.get_inputs():
            target = self.dfg.get_producing_instruction(op)
            assert target is not None, f"no producing instruction for {op}"
            if target.parent != inst.parent or target.fence_id != inst.fence_id:
                # don't reorder across basic block or fence boundaries
                continue
            self._process_instruction_r(bb, target, offset)

        # bb.instructions.append(inst)
        self.inst_order_num += 1
        self.inst_order[inst] = self.inst_order_num + offset

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self.ctx.append_basic_block(bb)

        for inst in bb.instructions:
            inst.fence_id = self.fence_id
            if inst.volatile:
                self.fence_id += 1

        self.inst_order = {}
        self.inst_order_num = 0
        for inst in bb.instructions:
            self._process_instruction_r(bb, inst)

        bb.instructions.sort(key=lambda x: self.inst_order[x])
        pass

    def _run_pass(self, ctx: IRFunction) -> None:
        self.ctx = ctx
        self.dfg = DFG.build_dfg(ctx)

        self.fence_id = 0
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        basic_blocks = ctx.basic_blocks
        ctx.basic_blocks = []

        for bb in basic_blocks:
            self._process_basic_block(bb)
