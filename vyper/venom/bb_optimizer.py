from vyper.utils import ir_pass
from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRInstruction, IRLabel
from vyper.venom.function import IRFunction


def _optimize_unused_variables(ctx: IRFunction) -> set[IRInstruction]:
    """
    Remove unused variables.
    """
    removeList = set()
    for bb in ctx.basic_blocks:
        for i, inst in enumerate(bb.instructions[:-1]):
            if inst.volatile:
                continue
            if inst.output and inst.output not in bb.instructions[i + 1].liveness:
                removeList.add(inst)

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
    return len(_optimize_unused_variables(ctx))
