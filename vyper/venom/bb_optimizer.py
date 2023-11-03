from vyper.utils import OrderedSet, ir_pass
from vyper.venom.basicblock import BB_TERMINATORS, IRBasicBlock, IRInstruction, IRLabel
from vyper.venom.function import IRFunction


def _optimize_unused_variables(ctx: IRFunction) -> list[IRInstruction]:
    """
    Remove unused variables.
    """
    removeList = []  # REVIEW: performance, could be `set()`
    for bb in ctx.basic_blocks:
        for i, inst in enumerate(bb.instructions[:-1]):
            if inst.volatile:
                continue
            if inst.ret and inst.ret not in bb.instructions[i + 1].liveness:
                removeList.append(inst)

        bb.instructions = [inst for inst in bb.instructions if inst not in removeList]

    return removeList


def _optimize_empty_basicblocks(ctx: IRFunction) -> int:
    """
    Remove empty basic blocks.
    """
    count = 0
    i = 0
    while i < len(ctx.basic_blocks):
        bb = ctx.basic_blocks[i]
        i += 1
        if len(bb.instructions) > 0:
            continue

        replaced_label = bb.label
        replacement_label = ctx.basic_blocks[i].label if i < len(ctx.basic_blocks) else None
        if replacement_label is None:
            continue

        # Try to preserve symbol labels
        if replaced_label.is_symbol:
            replaced_label, replacement_label = replacement_label, replaced_label
            ctx.basic_blocks[i].label = replacement_label

        for bb2 in ctx.basic_blocks:
            for inst in bb2.instructions:
                for op in inst.operands:
                    if isinstance(op, IRLabel) and op.value == replaced_label.value:
                        op.value = replacement_label.value

        ctx.basic_blocks.remove(bb)
        i -= 1
        count += 1

    return count


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
        in_vars = out_bb.in_vars_from(bb)
        bb.out_vars = bb.out_vars.union(in_vars)

    bb.calculate_liveness()


def calculate_liveness(ctx: IRFunction) -> None:
    _reset_liveness(ctx)
    _calculate_liveness(ctx.basic_blocks[0], OrderedSet())


@ir_pass
def ir_pass_optimize_empty_blocks(ctx: IRFunction) -> int:
    changes = _optimize_empty_basicblocks(ctx)
    calculate_cfg(ctx)
    return changes


@ir_pass
def ir_pass_remove_unreachable_blocks(ctx: IRFunction) -> int:
    return ctx.remove_unreachable_blocks()


@ir_pass
def ir_pass_optimize_unused_variables(ctx: IRFunction) -> int:
    return _optimize_unused_variables(ctx)
