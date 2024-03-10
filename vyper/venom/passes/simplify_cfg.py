from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class SimplifyCFGPass(IRPass):
    def _merge_blocks(self) -> None:
        ctx = self.ctx

        to_be_removed = []

        for bb in ctx.basic_blocks:
            if bb in to_be_removed:
                continue
            if len(bb.cfg_out) == 1:
                next = bb.cfg_out.first()
                if len(next.cfg_in) == 1:
                    bb.instructions.pop()
                    for inst in next.instructions:
                        assert inst.opcode != "phi", "Not implemented yet"
                        if inst.opcode == "phi":
                            bb.instructions.insert(0, inst)
                        else:
                            bb.instructions.append(inst)
                    bb.cfg_out = next.cfg_out

                    for n in next.cfg_out:
                        del n.cfg_in[next]
                        n.cfg_in.add(bb)

                    assert next in ctx.basic_blocks, next.label
                    to_be_removed.append(next)

        for bb in to_be_removed:
            # assert bb in ctx.basic_blocks, bb.label
            ctx.basic_blocks.remove(bb)

    def _run_pass(self, ctx: IRFunction) -> None:
        self.ctx = ctx

        self._merge_blocks()
