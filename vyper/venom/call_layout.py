from __future__ import annotations

from dataclasses import dataclass

from vyper.venom.basicblock import IRInstruction, IRLabel, IROperand, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction

# Internal-call layout conventions:
# - invoke operands are `[target, user args..., hidden_fmp?]`
# - callee params are `[user params..., hidden_fmp?, return_pc?]`
# User args/params stay in stable leading positions; hidden FMP, when
# present, lives at the tail.


@dataclass(frozen=True)
class FunctionCallLayout:
    fn: IRFunction

    @property
    def params(self) -> tuple[IRInstruction, ...]:
        return tuple(inst for inst in self.fn.entry.instructions if inst.opcode == "param")

    def param_for_alias(self, operand: IROperand) -> IRInstruction | None:
        aliases: dict[IRVariable, IRInstruction] = {inst.output: inst for inst in self.params}

        def lookup_alias(op: IROperand) -> IRInstruction | None:
            if not isinstance(op, IRVariable):
                return None
            return aliases.get(op)

        # This fixed-point walk is quadratic in the worst case. That is fine
        # for call-layout validation: functions have a small param frontier,
        # and this only needs enough precision to follow return-PC aliases.
        changed = True
        while changed:
            changed = False
            for bb in self.fn.get_basic_blocks():
                for inst in bb.instructions:
                    outputs = inst.get_outputs()
                    if len(outputs) != 1:
                        continue

                    source_param = None
                    if inst.opcode == "assign" and len(inst.operands) == 1:
                        source_param = lookup_alias(inst.operands[0])
                    elif inst.opcode == "phi":
                        source_params: list[IRInstruction] = []
                        for _, op in inst.phi_operands:
                            param = lookup_alias(op)
                            if param is None:
                                source_params = []
                                break
                            source_params.append(param)
                        if len(source_params) > 0 and len(set(source_params)) == 1:
                            source_param = source_params[0]

                    existing_param = aliases.get(outputs[0])
                    if source_param is None or existing_param == source_param:
                        continue
                    assert existing_param is None, (
                        self.fn.name,
                        outputs[0],
                        existing_param,
                        source_param,
                    )
                    aliases[outputs[0]] = source_param
                    changed = True

        return lookup_alias(operand)

    @property
    def has_return_pc_param(self) -> bool:
        if self.fn._invoke_param_count is not None:
            non_return_pc_params = self.fn._invoke_param_count + int(self.fn._needs_fmp)
            if len(self.params) > non_return_pc_params:
                return True

        for bb in self.fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "ret" or len(inst.operands) == 0:
                    continue

                ret_pc = inst.operands[-1]
                if self.param_for_alias(ret_pc) is not None:
                    return True

        return False

    @property
    def return_pc_param(self) -> IRInstruction | None:
        if not self.has_return_pc_param:
            return None

        params = self.params
        if len(params) == 0:
            return None
        return params[-1]

    @property
    def hidden_fmp_param_pos(self) -> int | None:
        if not self.fn._needs_fmp:
            return None

        return_pc_offset = int(self.has_return_pc_param)
        pos = len(self.params) - return_pc_offset - 1
        if self.fn._invoke_param_count is not None:
            # Metadata gives the authoritative hidden-FMP slot: after all
            # user invoke params and before return_pc, if any.
            assert pos == self.fn._invoke_param_count, (self.fn.name, pos)

        if pos < 0:
            return None
        return pos

    @property
    def hidden_fmp_param(self) -> IRInstruction | None:
        pos = self.hidden_fmp_param_pos
        if pos is None:
            return None

        params = self.params
        if pos >= len(params):
            return None
        return params[pos]

    @property
    def hidden_fmp_param_insert_index(self) -> int:
        return_pc = self.return_pc_param
        if return_pc is not None:
            return self.fn.entry.instructions.index(return_pc)

        params = self.params
        if len(params) == 0:
            return 0
        return self.fn.entry.instructions.index(params[-1]) + 1

    @property
    def user_params(self) -> tuple[IRInstruction, ...]:
        count = len(self.params)
        count -= int(self.has_return_pc_param)
        count -= int(self.fn._needs_fmp)
        return self.params[: max(count, 0)]

    @property
    def physical_user_param_count(self) -> int:
        return len(self.user_params)

    @property
    def expected_user_arg_count(self) -> int:
        if self.fn._invoke_param_count is not None:
            return self.fn._invoke_param_count
        return self.physical_user_param_count


@dataclass(frozen=True)
class InvokeLayout:
    ctx: IRContext
    inst: IRInstruction
    callee_override: IRFunction | None = None

    @property
    def target(self) -> IROperand | None:
        if len(self.inst.operands) == 0:
            return None
        return self.inst.operands[0]

    @property
    def callee(self) -> IRFunction | None:
        if self.callee_override is not None:
            return self.callee_override

        target = self.target
        if not isinstance(target, IRLabel):
            return None
        return self.ctx.functions.get(target)

    @property
    def callee_layout(self) -> FunctionCallLayout | None:
        callee = self.callee
        if callee is None:
            return None
        return FunctionCallLayout(callee)

    @property
    def expects_hidden_fmp(self) -> bool:
        callee = self.callee
        return callee is not None and callee._needs_fmp

    @property
    def expected_operand_count(self) -> int | None:
        callee_layout = self.callee_layout
        if callee_layout is None:
            return None
        return 1 + callee_layout.expected_user_arg_count + int(self.expects_hidden_fmp)

    @property
    def hidden_fmp_operand_pos(self) -> int | None:
        if not self.expects_hidden_fmp:
            return None
        if len(self.inst.operands) <= 1:
            return None
        return len(self.inst.operands) - 1

    @property
    def hidden_fmp_operand(self) -> IROperand | None:
        pos = self.hidden_fmp_operand_pos
        if pos is None:
            return None
        return self.inst.operands[pos]

    @property
    def user_operands(self) -> tuple[IROperand, ...]:
        if len(self.inst.operands) <= 1:
            return ()

        ops = tuple(self.inst.operands[1:])
        if self.expects_hidden_fmp and self.hidden_fmp_operand_pos is not None:
            return ops[:-1]
        return ops

    @property
    def user_arg_count(self) -> int:
        return len(self.user_operands)

    @property
    def actual_operand_count_after_target(self) -> int:
        return max(len(self.inst.operands) - 1, 0)

    def user_arg_index(self, operand_idx: int) -> int | None:
        if operand_idx <= 0:
            return None

        hidden_fmp_pos = self.hidden_fmp_operand_pos
        if operand_idx == hidden_fmp_pos:
            return None
        if hidden_fmp_pos is not None and operand_idx > hidden_fmp_pos:
            return None

        return operand_idx - 1

    @property
    def return_buffer_operand_pos(self) -> int | None:
        callee = self.callee
        callee_layout = self.callee_layout
        if callee is None or callee_layout is None:
            return None
        if callee._invoke_param_count is None or callee._has_memory_return_buffer_param is None:
            return None
        if self.user_arg_count != callee_layout.expected_user_arg_count:
            return None
        if not callee._has_memory_return_buffer_param:
            return None

        return 1

    @property
    def bound_params(self) -> tuple[IROperand, ...]:
        operands = list(self.user_operands)

        hidden_fmp_operand = self.hidden_fmp_operand
        if hidden_fmp_operand is not None:
            operands.append(hidden_fmp_operand)

        target = self.target
        if target is not None:
            operands.append(target)

        return tuple(operands)

    def append_hidden_fmp_operand(self, fmp_var: IROperand) -> None:
        self.inst.operands = [*self.inst.operands, fmp_var]

    def remove_trailing_operand(self) -> None:
        self.inst.operands.pop()


def function_has_return_pc_param(fn: IRFunction) -> bool:
    return FunctionCallLayout(fn).has_return_pc_param


def get_param_instructions(fn: IRFunction) -> tuple[IRInstruction, ...]:
    return FunctionCallLayout(fn).params


def get_user_param_instructions(fn: IRFunction) -> tuple[IRInstruction, ...]:
    return FunctionCallLayout(fn).user_params


def get_return_pc_param_inst(fn: IRFunction) -> IRInstruction | None:
    return FunctionCallLayout(fn).return_pc_param


def get_hidden_fmp_param_inst(fn: IRFunction) -> IRInstruction | None:
    return FunctionCallLayout(fn).hidden_fmp_param


def get_hidden_fmp_param_insert_index(fn: IRFunction) -> int:
    return FunctionCallLayout(fn).hidden_fmp_param_insert_index


def get_invoke_callee(ctx: IRContext, invoke_inst: IRInstruction) -> IRFunction | None:
    return InvokeLayout(ctx, invoke_inst).callee


def get_invoke_hidden_fmp_operand_pos(
    invoke_inst: IRInstruction, callee: IRFunction | None
) -> int | None:
    if callee is None:
        return None
    return InvokeLayout(callee.ctx, invoke_inst, callee).hidden_fmp_operand_pos


def get_invoke_user_operands(
    invoke_inst: IRInstruction, callee: IRFunction | None
) -> tuple[IROperand, ...]:
    if callee is None:
        if len(invoke_inst.operands) <= 1:
            return ()
        return tuple(invoke_inst.operands[1:])
    return InvokeLayout(callee.ctx, invoke_inst, callee).user_operands


def get_invoke_user_arg_count(invoke_inst: IRInstruction, callee: IRFunction | None) -> int:
    if callee is None:
        return len(get_invoke_user_operands(invoke_inst, callee))
    return InvokeLayout(callee.ctx, invoke_inst, callee).user_arg_count


def get_invoke_user_arg_index(
    invoke_inst: IRInstruction, operand_idx: int, callee: IRFunction | None
) -> int | None:
    if callee is None:
        if operand_idx <= 0:
            return None
        return operand_idx - 1
    return InvokeLayout(callee.ctx, invoke_inst, callee).user_arg_index(operand_idx)


def get_invoke_return_buffer_operand_pos(
    invoke_inst: IRInstruction, callee: IRFunction | None
) -> int | None:
    if callee is None:
        return None
    return InvokeLayout(callee.ctx, invoke_inst, callee).return_buffer_operand_pos


def get_invoke_bound_params(
    invoke_inst: IRInstruction, callee: IRFunction | None
) -> tuple[IROperand, ...]:
    if callee is None:
        ops = list(get_invoke_user_operands(invoke_inst, None))
        if len(invoke_inst.operands) > 0:
            ops.append(invoke_inst.operands[0])
        return tuple(ops)
    return InvokeLayout(callee.ctx, invoke_inst, callee).bound_params
