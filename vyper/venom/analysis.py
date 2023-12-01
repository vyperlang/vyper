from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.basicblock import (
    BB_TERMINATORS,
    CFG_ALTERING_OPS,
    IRBasicBlock,
    IRInstruction,
    IRVariable,
)
from vyper.venom.function import IRFunction


def calculate_cfg(ctx: IRFunction) -> None:
    """
    Calculate (cfg) inputs for each basic block.
    """
    for bb in ctx.basic_blocks:
        bb.cfg_in = OrderedSet()
        bb.cfg_out = OrderedSet()
        bb.out_vars = OrderedSet()

    # TODO: This is a hack to support the old IR format where `deploy` is
    # an instruction. in the future we should have two entry points, one
    # for the initcode and one for the runtime code.
    deploy_bb = None
    after_deploy_bb = None
    for i, bb in enumerate(ctx.basic_blocks):
        if bb.instructions[0].opcode == "deploy":
            deploy_bb = bb
            after_deploy_bb = ctx.basic_blocks[i + 1]
            break

    if deploy_bb is not None:
        assert after_deploy_bb is not None, "No block after deploy block"
        entry_block = after_deploy_bb
        has_constructor = ctx.basic_blocks[0].instructions[0].opcode != "deploy"
        if has_constructor:
            deploy_bb.add_cfg_in(ctx.basic_blocks[0])
            entry_block.add_cfg_in(deploy_bb)
    else:
        entry_block = ctx.basic_blocks[0]

    # TODO: Special case for the jump table of selector buckets and fallback.
    # this will be cleaner when we introduce an "indirect jump" instruction
    # for the selector table (which includes all possible targets). it will
    # also clean up the code for normalization because it will not have to
    # handle this case specially.
    for bb in ctx.basic_blocks:
        if "selector_bucket_" in bb.label.value or bb.label.value == "fallback":
            bb.add_cfg_in(entry_block)

    for bb in ctx.basic_blocks:
        assert len(bb.instructions) > 0, "Basic block should not be empty"
        last_inst = bb.instructions[-1]
        assert last_inst.opcode in BB_TERMINATORS, f"Last instruction should be a terminator {bb}"

        for inst in bb.instructions:
            if inst.opcode in CFG_ALTERING_OPS:
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


def _calculate_liveness_bb(bb: IRBasicBlock) -> None:
    """
    Compute liveness of each instruction in the basic block.
    """
    liveness = bb.out_vars.copy()
    for instruction in reversed(bb.instructions):
        ops = instruction.get_inputs()

        for op in ops:
            if op in liveness:
                instruction.dup_requirements.add(op)

        liveness = liveness.union(OrderedSet.fromkeys(ops))
        out = instruction.get_outputs()[0] if len(instruction.get_outputs()) > 0 else None
        if out in liveness:
            liveness.remove(out)
        instruction.liveness = liveness


def _calculate_liveness_r(bb: IRBasicBlock, visited: dict) -> None:
    assert isinstance(visited, dict)
    for out_bb in bb.cfg_out:
        if visited.get(bb) == out_bb:
            continue
        visited[bb] = out_bb

        # recurse
        _calculate_liveness_r(out_bb, visited)

        target_vars = input_vars_from(bb, out_bb)

        # the output stack layout for bb. it produces a stack layout
        # which works for all possible cfg_outs from the bb.
        bb.out_vars = bb.out_vars.union(target_vars)

    _calculate_liveness_bb(bb)


def calculate_liveness(ctx: IRFunction) -> None:
    _reset_liveness(ctx)
    _calculate_liveness_r(ctx.basic_blocks[0], dict())


# calculate the input variables into self from source
def input_vars_from(source: IRBasicBlock, target: IRBasicBlock) -> OrderedSet[IRVariable]:
    liveness = target.instructions[0].liveness.copy()
    assert isinstance(liveness, OrderedSet)

    for inst in target.instructions:
        if inst.opcode == "phi":
            # we arbitrarily choose one of the arguments to be in the
            # live variables set (dependent on how we traversed into this
            # basic block). the argument will be replaced by the destination
            # operand during instruction selection.
            # for instance, `%56 = phi %label1 %12 %label2 %14`
            # will arbitrarily choose either %12 or %14 to be in the liveness
            # set, and then during instruction selection, after this instruction,
            # %12 will be replaced by %56 in the liveness set
            source1, source2 = inst.operands[0], inst.operands[2]
            phi1, phi2 = inst.operands[1], inst.operands[3]
            if source.label == source1:
                liveness.add(phi1)
                if phi2 in liveness:
                    liveness.remove(phi2)
            elif source.label == source2:
                liveness.add(phi2)
                if phi1 in liveness:
                    liveness.remove(phi1)
            else:
                # bad path into this phi node
                raise CompilerPanic(f"unreachable: {inst}")

    return liveness


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
    def build_dfg(cls, ctx: IRFunction) -> "DFG":
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

                for op in res:  # type: ignore
                    dfg._dfg_outputs[op] = inst

        return dfg
