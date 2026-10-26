from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from vyper.venom.basicblock import (
    RET_INSTRUCTIONS,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction

# Internal-call layout conventions:
# - invoke operands are `[target, user args..., hidden_fmp?]`
# - callee params are `[user params..., hidden_fmp?, return_pc?]`
# User args/params stay in stable leading positions; hidden FMP, when
# present, lives at the tail (named by the dedicated `fmp_param` opcode).
#
# The return-PC param is identified at two levels:
# - The `retpc_param` opcode names it syntactically (emitted by the
#   frontend and by FmpLoweringPass; mandatory in lowered IR).
# - In RAW IR a plain `param` may serve as the return PC. There it is
#   *defined* as the unique param that the last operand of a
#   `ret`/`dret`/`retfmp` aliases -- this ret-anchored discovery is the
#   raw-level definition of the return PC, not a heuristic. Lowered
#   (annotated) functions get no such discovery: their convention is
#   carried by opcodes only.


def parse_dret_shape(inst: IRInstruction) -> tuple[int, int] | None:
    """
    Decode a `dret` instruction's operand layout into `(ordinary_count,
    dyn_count)`, or None if the operands are malformed.

    dret operands are `[dyn_count, ordinary returns..., (src, size) pairs...,
    return_pc]`, with `dyn_count` dynamic (src, size) pairs.
    """
    if len(inst.operands) < 4:
        return None

    dyn_count_op = inst.operands[0]
    if not isinstance(dyn_count_op, IRLiteral):
        return None

    dyn_count = dyn_count_op.value
    if dyn_count < 1:
        return None

    ordinary_count = len(inst.operands) - 2 - 2 * dyn_count
    if ordinary_count < 0:
        return None

    return ordinary_count, dyn_count


def has_dret(fn: IRFunction) -> bool:
    return any(inst.opcode == "dret" for bb in fn.get_basic_blocks() for inst in bb.instructions)


@dataclass(frozen=True)
class FunctionCallLayout:
    fn: IRFunction

    @property
    def params(self) -> tuple[IRInstruction, ...]:
        return tuple(inst for inst in self.fn.entry.instructions if inst.is_param)

    @property
    def hidden_fmp_param(self) -> IRInstruction | None:
        # syntactic hidden-FMP param, created by FmpLoweringPass
        for inst in self.fn.entry.instructions:
            if inst.opcode == "fmp_param":
                return inst
        return None

    @property
    def retpc_param_opcode_inst(self) -> IRInstruction | None:
        # syntactic return-PC param, emitted by the frontend and by
        # FmpLoweringPass
        for inst in self.fn.entry.instructions:
            if inst.opcode == "retpc_param":
                return inst
        return None

    def param_for_alias(self, operand: IROperand) -> IRInstruction | None:
        if not isinstance(operand, IRVariable):
            return None
        return self._param_aliases.get(operand)

    @cached_property
    def _param_aliases(self) -> dict[IRVariable, IRInstruction | None]:
        # Computed once per layout instance (layouts are built fresh per
        # query site, so the cache never outlives an IR mutation).
        #
        # A `None` value is a demotion sentinel: the variable has conflicting
        # definitions from different params (valid in pre-SSA IR, which MakeSSA
        # repairs), so it is "not a unique param alias". Lookups on demoted
        # variables return None and demotion stops further propagation.
        aliases: dict[IRVariable, IRInstruction | None] = {
            inst.output: inst for inst in self.params
        }

        def lookup_alias(op: IROperand) -> IRInstruction | None:
            if not isinstance(op, IRVariable):
                return None
            return aliases.get(op)

        # Iteration to fixpoint, not a single sweep: a loop-header phi's
        # back-edge operand is defined later in block order, so its
        # param-aliasing is only discovered on a later sweep; and pre-SSA
        # parsed IR (the validator path) has no def-before-use order at all.
        # The walk is quadratic in the worst case. That is fine for
        # call-layout validation: functions have a small param frontier,
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
                    # a non-param redefinition (source_param is None) does not
                    # demote: this map only *identifies* which param slot the
                    # rets anchor (raw-IR convention discovery / validation),
                    # never the runtime value at the use site; FmpLoweringPass
                    # itself runs post-MakeSSA, where multi-def is impossible.
                    if source_param is None or existing_param == source_param:
                        continue
                    if outputs[0] in aliases:
                        # Conflicting definitions (multi-def pre-SSA variable):
                        # demote to "not a unique param alias".
                        if existing_param is not None:
                            aliases[outputs[0]] = None
                            changed = True
                        continue
                    aliases[outputs[0]] = source_param
                    changed = True

        return aliases

    @property
    def is_lowered(self) -> bool:
        # the FMP convention has been frozen (by FmpLoweringPass or the
        # parsed function-header annotation); the layout is syntax-only
        return self.fn._fmp_signature is not None

    @property
    def return_pc_param(self) -> IRInstruction | None:
        retpc_inst = self.retpc_param_opcode_inst
        if retpc_inst is not None:
            return retpc_inst

        if self.is_lowered:
            # lowered IR carries its convention in opcodes only; a plain
            # param is never the return PC here (the input validator
            # rejects lowered functions whose ret anchors a plain param)
            return None

        # raw-level definition: the return PC is the param that the rets
        # anchor (see module docstring)
        return self._return_pc_param_from_ret

    @property
    def _return_pc_param_from_ret(self) -> IRInstruction | None:
        for bb in self.fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode not in RET_INSTRUCTIONS or len(inst.operands) == 0:
                    continue

                ret_pc = inst.operands[-1]
                param = self.param_for_alias(ret_pc)
                if param is not None:
                    return param

        return None

    @property
    def has_return_pc_param(self) -> bool:
        return self.return_pc_param is not None

    @property
    def has_physical_hidden_fmp_param(self) -> bool:
        # purely syntactic: the hidden FMP param exists iff the dedicated
        # opcode does
        return self.hidden_fmp_param is not None

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
        hidden = {self.hidden_fmp_param, self.return_pc_param}
        return tuple(inst for inst in self.params if inst not in hidden)

    @property
    def expected_user_arg_count(self) -> int:
        return len(self.user_params)


@dataclass(frozen=True)
class InvokeLayout:
    ctx: IRContext
    inst: IRInstruction

    @property
    def target(self) -> IROperand | None:
        if len(self.inst.operands) == 0:
            return None
        return self.inst.operands[0]

    @property
    def callee(self) -> IRFunction | None:
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
        callee_layout = self.callee_layout
        return callee_layout is not None and callee_layout.has_physical_hidden_fmp_param

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
        if callee._has_memory_return_buffer_param is None:
            return None
        # replaces the old frontend-side `_invoke_param_count` arity guard:
        # post-lowering the physical arity gains a hidden fmp operand, so the
        # expected *user* arg count is derived from the callee's entry params
        # minus the hidden fmp/retpc params -- identical to the old count on
        # raw IR.
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

    def append_hidden_fmp_output(self, fmp_var: IRVariable) -> None:
        self.inst.set_outputs([*self.inst.get_outputs(), fmp_var])
