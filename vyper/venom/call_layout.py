from __future__ import annotations

from vyper.venom.basicblock import IRInstruction, IRLabel, IROperand
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction


# Internal-call layout conventions:
# - invoke operands are `[target, user args..., hidden_fmp?]`
# - callee params are `[user params..., hidden_fmp?, return_pc?]`
# User args/params stay in stable leading positions; hidden FMP, when
# present, lives at the tail.

def function_has_return_pc_param(fn: IRFunction) -> bool:
    for bb in fn.get_basic_blocks():
        for inst in bb.instructions:
            if inst.opcode == "ret":
                return True
    return False


def get_param_instructions(fn: IRFunction) -> tuple[IRInstruction, ...]:
    return tuple(fn.entry.param_instructions)


def get_user_param_instructions(fn: IRFunction) -> tuple[IRInstruction, ...]:
    params = get_param_instructions(fn)
    if len(params) == 0:
        return ()

    if fn._invoke_param_count is not None:
        return params[: fn._invoke_param_count]

    count = len(params)
    if function_has_return_pc_param(fn):
        count -= 1
    if fn._has_fmp_param:
        count -= 1
    return params[: max(count, 0)]


def get_return_pc_param_inst(fn: IRFunction) -> IRInstruction | None:
    if not function_has_return_pc_param(fn):
        return None

    params = get_param_instructions(fn)
    if len(params) == 0:
        return None
    return params[-1]


def get_hidden_fmp_param_inst(fn: IRFunction) -> IRInstruction | None:
    if not fn._has_fmp_param:
        return None

    params = get_param_instructions(fn)
    if len(params) == 0:
        return None

    if function_has_return_pc_param(fn):
        if len(params) < 2:
            return None
        return params[-2]

    return params[-1]


def get_hidden_fmp_param_insert_index(fn: IRFunction) -> int:
    params = get_param_instructions(fn)
    return len(params) - int(function_has_return_pc_param(fn))


def get_invoke_callee(ctx: IRContext, invoke_inst: IRInstruction) -> IRFunction | None:
    target = invoke_inst.operands[0]
    if not isinstance(target, IRLabel):
        return None
    return ctx.functions.get(target)


def get_invoke_hidden_fmp_operand_pos(
    invoke_inst: IRInstruction, callee: IRFunction | None
) -> int | None:
    if callee is None or not callee._has_fmp_param:
        return None
    return len(invoke_inst.operands) - 1


def get_invoke_user_operands(
    invoke_inst: IRInstruction, callee: IRFunction | None
) -> tuple[IROperand, ...]:
    ops = tuple(invoke_inst.operands[1:])
    if callee is not None and callee._has_fmp_param:
        return ops[:-1]
    return ops


def get_invoke_user_arg_count(invoke_inst: IRInstruction, callee: IRFunction | None) -> int:
    return len(get_invoke_user_operands(invoke_inst, callee))


def get_invoke_user_arg_index(
    invoke_inst: IRInstruction, operand_idx: int, callee: IRFunction | None
) -> int | None:
    if operand_idx <= 0:
        return None

    hidden_fmp_pos = get_invoke_hidden_fmp_operand_pos(invoke_inst, callee)
    if operand_idx == hidden_fmp_pos:
        return None

    return operand_idx - 1


def get_invoke_return_buffer_operand_pos(
    invoke_inst: IRInstruction, callee: IRFunction | None
) -> int | None:
    if callee is None:
        return None
    if callee._invoke_param_count is None or callee._has_memory_return_buffer_param is None:
        return None

    if get_invoke_user_arg_count(invoke_inst, callee) != callee._invoke_param_count:
        return None
    if not callee._has_memory_return_buffer_param:
        return None

    return 1


def get_invoke_bound_params(
    invoke_inst: IRInstruction, callee: IRFunction | None
) -> tuple[IROperand, ...]:
    user_ops = list(get_invoke_user_operands(invoke_inst, callee))

    hidden_fmp_pos = get_invoke_hidden_fmp_operand_pos(invoke_inst, callee)
    if hidden_fmp_pos is not None:
        user_ops.append(invoke_inst.operands[hidden_fmp_pos])

    user_ops.append(invoke_inst.operands[0])
    return tuple(user_ops)
