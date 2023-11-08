from vyper.utils import OrderedSet
from vyper.venom.basicblock import BB_TERMINATORS, IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.function import IRFunction


def calculate_cfg(ctx: IRFunction) -> None:
    """
    Calculate (cfg) inputs for each basic block.
    """
    for bb in ctx.basic_blocks:
        bb.cfg_in = OrderedSet()
        bb.cfg_out = OrderedSet()
        bb.out_vars = OrderedSet()

    deploy_bb = None
    after_deploy_bb = None
    for i, bb in enumerate(ctx.basic_blocks):
        if bb.instructions[0].opcode == "deploy":
            deploy_bb = bb
            after_deploy_bb = ctx.basic_blocks[i + 1]
            break

    if deploy_bb:
        entry_block = after_deploy_bb
        has_constructor = True if ctx.basic_blocks[0].instructions[0].opcode != "deploy" else False
        if has_constructor:
            deploy_bb.add_cfg_in(ctx.basic_blocks[0])
            entry_block.add_cfg_in(deploy_bb)
    else:
        entry_block = ctx.basic_blocks[0]

    for bb in ctx.basic_blocks:
        if "selector_bucket_" in bb.label.value or bb.label.value == "fallback":
            bb.add_cfg_in(entry_block)

    for bb in ctx.basic_blocks:
        assert len(bb.instructions) > 0, "Basic block should not be empty"
        last_inst = bb.instructions[-1]
        assert last_inst.opcode in BB_TERMINATORS, "Last instruction should be a terminator" + str(
            bb
        )

        for inst in bb.instructions:
            if inst.opcode in ["jmp", "jnz", "call", "staticcall", "invoke", "deploy"]:
                ops = inst.get_label_operands()
                for op in ops:
                    ctx.get_basic_block(op.value).add_cfg_in(bb)

    # Fill in the "out" set for each basic block
    for bb in ctx.basic_blocks:
        for in_bb in bb.cfg_in:
            in_bb.add_cfg_out(bb)


def _reset_liveness(ctx: IRFunction) -> None:
    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            inst.liveness = OrderedSet()


def _calculate_liveness(bb: IRBasicBlock, liveness_visited: OrderedSet) -> None:
    assert isinstance(liveness_visited, OrderedSet)
    for out_bb in bb.cfg_out:
        if liveness_visited.get(bb) == out_bb:
            continue
        liveness_visited[bb] = out_bb
        _calculate_liveness(out_bb, liveness_visited)
        target_vars = out_bb.in_vars_from(bb)
        bb.out_vars = bb.out_vars.union(target_vars)

    bb.calculate_liveness()


def calculate_liveness(ctx: IRFunction) -> None:
    _reset_liveness(ctx)
    _calculate_liveness(ctx.basic_blocks[0], OrderedSet())


# DataFlow Graph
# this could be refactored into its own file, but it's only used here
# for now
class DFG:
    _dfg_inputs: dict[IRVariable, list[IRInstruction]]
    _dfg_outputs: dict[IRVariable, IRInstruction]

    def __init__(self):
        self._dfg_inputs = dict()
        self._dfg_outputs = dict()

    # return uses of a given variable
    def get_uses(self, op: IRVariable) -> list[IRInstruction]:
        return self._dfg_inputs.get(op, [])

    # the instruction which produces this variable.
    def get_producing_instruction(self, op: IRVariable) -> IRInstruction:
        return self._dfg_outputs[op]

    @classmethod
    def build_dfg(cls, ctx: IRFunction):
        dfg = cls()

        # Build DFG

        # %15 = add %13 %14
        # %16 = iszero %15
        # dfg_outputs of %15 is (%15 = add %13 %14)
        # dfg_inputs of %15 is all the instructions which *use* %15, ex. [(%16 = iszero %15), ...]
        for bb in ctx.basic_blocks:
            for inst in bb.instructions:
                operands = inst.get_inputs()
                res = inst.get_outputs()

                for op in operands:
                    inputs = dfg._dfg_inputs.setdefault(op, [])
                    inputs.append(inst)

                for op in res:
                    dfg._dfg_outputs[op] = inst

        return dfg
