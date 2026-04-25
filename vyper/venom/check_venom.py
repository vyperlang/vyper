from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import IRAnalysesCache, VarDefinition
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.call_layout import FunctionCallLayout, InvokeLayout
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import (
    get_memory_read_op,
    get_memory_write_op,
    get_read_size,
    get_write_max_size,
)


class VenomError(Exception):
    message: str


class BasicBlockNotTerminated(VenomError):
    message: str = "basic block does not terminate"

    def __init__(self, basicblock):
        self.basicblock = basicblock

    def __str__(self):
        return f"basic block is not terminated:\n{self.basicblock}"


class VarNotDefined(VenomError):
    message: str = "variable is used before definition"

    def __init__(self, var, inst):
        self.var = var
        self.inst = inst

    def __str__(self):
        bb = self.inst.parent
        return f"var {self.var} not defined:\n  {self.inst}\n\n{bb}"


class InconsistentReturnArity(VenomError):
    message: str = "function has inconsistent return arity"

    def __init__(self, function: IRFunction, arities: set[int]):
        self.function = function
        self.arities = arities

    def __str__(self):
        return (
            f"function {self.function.name} has inconsistent 'ret' arities: {sorted(self.arities)}"
        )


class InvokeArityMismatch(VenomError):
    message: str = "invoke outputs do not match callee return arity"

    def __init__(self, caller: IRFunction, inst: IRInstruction, expected: int, got: int):
        self.caller = caller
        self.inst = inst
        self.expected = expected
        self.got = got

    def __str__(self):
        bb = self.inst.parent
        return (
            f"invoke arity mismatch in {self.caller.name}: "
            f"expected {self.expected}, got {self.got}\n"
            f"  {self.inst}\n\n{bb}"
        )


class InvokeTargetError(VenomError):
    message: str = "invoke target must be a function label"

    def __init__(self, caller: IRFunction, inst: IRInstruction):
        self.caller = caller
        self.inst = inst

    def __str__(self):
        bb = self.inst.parent
        return f"invoke target error in {self.caller.name}:\n" f"  {self.inst}\n\n{bb}"


class InvokeArgumentCountMismatch(VenomError):
    message: str = "invoke arguments do not match callee params"

    def __init__(
        self,
        caller: IRFunction,
        callee: IRFunction,
        inst: IRInstruction,
        expected_user_args: int,
        expected_hidden_fmp_args: int,
        got_args_after_target: int,
    ):
        self.caller = caller
        self.callee = callee
        self.inst = inst
        self.expected_user_args = expected_user_args
        self.expected_hidden_fmp_args = expected_hidden_fmp_args
        self.got_args_after_target = got_args_after_target

    def __str__(self):
        bb = self.inst.parent
        expected = self.expected_user_args + self.expected_hidden_fmp_args
        return (
            f"invoke argument mismatch in {self.caller.name} calling {self.callee.name}: "
            f"expected {expected} arg(s) after target "
            f"({self.expected_user_args} user, {self.expected_hidden_fmp_args} hidden FMP), "
            f"got {self.got_args_after_target}\n"
            f"  {self.inst}\n\n{bb}"
        )


class FunctionCallLayoutError(VenomError):
    message: str = "function call layout metadata is inconsistent"

    def __init__(self, function: IRFunction, detail: str):
        self.function = function
        self.detail = detail

    def __str__(self):
        return f"function {self.function.name} has invalid call layout: {self.detail}"


class MultiOutputNonInvoke(VenomError):
    message: str = "multi-output assignment only supported for invoke"

    def __init__(self, caller: IRFunction, inst: IRInstruction):
        self.caller = caller
        self.inst = inst

    def __str__(self):
        bb = self.inst.parent
        return f"multi-output on non-invoke in {self.caller.name}:\n" f"  {self.inst}\n\n{bb}"


class BumpArityError(VenomError):
    message: str = "bump must have exactly 2 operands and 2 outputs"

    def __init__(self, caller: IRFunction, inst: IRInstruction):
        self.caller = caller
        self.inst = inst

    def __str__(self):
        bb = self.inst.parent
        return (
            f"bump arity error in {self.caller.name}: "
            f"got {len(self.inst.operands)} operand(s), {self.inst.num_outputs} output(s)\n"
            f"  {self.inst}\n\n{bb}"
        )


class DallocaArityError(VenomError):
    message: str = "dalloca must have exactly 1 operand and 2 outputs"

    def __init__(self, caller: IRFunction, inst: IRInstruction):
        self.caller = caller
        self.inst = inst

    def __str__(self):
        bb = self.inst.parent
        return (
            f"dalloca arity error in {self.caller.name}: "
            f"got {len(self.inst.operands)} operand(s), {self.inst.num_outputs} output(s)\n"
            f"  {self.inst}\n\n{bb}"
        )


class DfreeArityError(VenomError):
    message: str = "dfree must have exactly 1 operand and 0 outputs"

    def __init__(self, caller: IRFunction, inst: IRInstruction):
        self.caller = caller
        self.inst = inst

    def __str__(self):
        bb = self.inst.parent
        return (
            f"dfree arity error in {self.caller.name}: "
            f"got {len(self.inst.operands)} operand(s), {self.inst.num_outputs} output(s)\n"
            f"  {self.inst}\n\n{bb}"
        )


class UnsupportedInstruction(VenomError):
    message: str = "unsupported instruction"

    def __init__(self, caller: IRFunction, inst: IRInstruction, detail: str):
        self.caller = caller
        self.inst = inst
        self.detail = detail

    def __str__(self):
        bb = self.inst.parent
        return (
            f"unsupported instruction in {self.caller.name}: {self.detail}\n  {self.inst}\n\n{bb}"
        )


def _handle_var_definition(
    fn: IRFunction, bb: IRBasicBlock, var_def: VarDefinition
) -> list[VenomError]:
    errors: list[VenomError] = []
    for inst in bb.instructions:
        if inst.opcode == "phi":
            for label, op in inst.phi_operands:
                defined = var_def.defined_vars_bb[fn.get_basic_block(label.name)]
                if op not in defined:
                    errors.append(VarNotDefined(var=op, inst=inst))
            continue
        defined = var_def.defined_vars[inst]
        for op in inst.operands:
            if isinstance(op, IRVariable):
                if op not in defined:
                    errors.append(VarNotDefined(var=op, inst=inst))
    return errors


def find_semantic_errors_fn(fn: IRFunction) -> list[VenomError]:
    errors: list[VenomError] = []

    # check that all the bbs are terminated
    for bb in fn.get_basic_blocks():
        if not bb.is_terminated:
            errors.append(BasicBlockNotTerminated(basicblock=bb))

    if len(errors) > 0:
        return errors

    ac = IRAnalysesCache(fn)
    var_def: VarDefinition = ac.request_analysis(VarDefinition)
    for bb in fn.get_basic_blocks():
        e = _handle_var_definition(fn, bb, var_def)
        errors.extend(e)
    return errors


def _collect_ret_arities(context: IRContext) -> dict[IRFunction, set[int]]:
    ret_arities: dict[IRFunction, set[int]] = {}
    for fn in context.functions.values():
        arities: set[int] = set()
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "ret":
                    # last operand is return PC; all preceding (if any) are return values
                    arities.add(len(inst.operands) - 1)

        ret_arities[fn] = arities

    return ret_arities


def _find_function_call_layout_errors(fn: IRFunction) -> list[VenomError]:
    errors: list[VenomError] = []
    layout = FunctionCallLayout(fn)

    if layout.has_return_pc_param:
        return_pc = layout.return_pc_param
        if return_pc is None:
            errors.append(FunctionCallLayoutError(fn, "return-PC param is missing"))
        else:
            param_outputs = {inst.output for inst in layout.params}
            return_pc_var = return_pc.output
            for bb in fn.get_basic_blocks():
                for inst in bb.instructions:
                    if inst.opcode != "ret" or len(inst.operands) == 0:
                        continue
                    ret_pc = inst.operands[-1]
                    ret_pc_param = layout.param_for_alias(ret_pc)
                    if (
                        ret_pc_param is not None
                        and ret_pc_param.output in param_outputs
                        and ret_pc_param.output != return_pc_var
                    ):
                        errors.append(
                            FunctionCallLayoutError(
                                fn, "return-PC param must be the final function param"
                            )
                        )
                        return errors

    if fn._has_fmp_param and layout.hidden_fmp_param is None:
        errors.append(FunctionCallLayoutError(fn, "hidden FMP param is missing"))

    if fn._invoke_param_count is not None:
        if fn._invoke_param_count < 0:
            errors.append(FunctionCallLayoutError(fn, "_invoke_param_count cannot be negative"))
        elif layout.physical_user_param_count != fn._invoke_param_count:
            errors.append(
                FunctionCallLayoutError(
                    fn,
                    "_invoke_param_count does not match physical user params: "
                    f"expected {layout.physical_user_param_count}, got {fn._invoke_param_count}",
                )
            )

    if fn._has_memory_return_buffer_param and (
        fn._invoke_param_count is None or fn._invoke_param_count == 0
    ):
        errors.append(
            FunctionCallLayoutError(
                fn, "memory return buffer metadata requires at least one invoke param"
            )
        )

    return errors


def find_calling_convention_errors(context: IRContext) -> list[VenomError]:
    errors: list[VenomError] = []

    # Enforce invoke binding exactly callee arity
    ret_arities = _collect_ret_arities(context)

    for fn, arities in ret_arities.items():
        errors.extend(_find_function_call_layout_errors(fn))

        if len(arities) > 1:
            errors.append(InconsistentReturnArity(fn, arities))

    for caller in context.functions.values():
        for bb in caller.get_basic_blocks():
            for inst in bb.instructions:
                # Disallow multi-output except on invoke, bump, and dalloca.
                got_num = inst.num_outputs
                if got_num > 1 and inst.opcode not in ("invoke", "bump", "dalloca"):
                    errors.append(MultiOutputNonInvoke(caller, inst))
                    continue
                if inst.opcode == "bump":
                    # bump has a fixed stack shape (DUP2; ADD) with two inputs
                    # and two outputs; any other shape is malformed.
                    if len(inst.operands) != 2 or got_num != 2:
                        errors.append(BumpArityError(caller, inst))
                    continue
                if inst.opcode == "dalloca":
                    if len(inst.operands) != 1 or got_num != 2:
                        errors.append(DallocaArityError(caller, inst))
                    continue
                if inst.opcode == "dfree":
                    if len(inst.operands) != 1 or got_num != 0:
                        errors.append(DfreeArityError(caller, inst))
                    continue
                if inst.opcode == "memtop":
                    errors.append(
                        UnsupportedInstruction(
                            caller, inst, "`memtop` has been removed; use `dalloca` instead"
                        )
                    )
                    continue
                if inst.opcode != "invoke":
                    continue
                layout = InvokeLayout(context, inst)
                target = layout.target
                callee = layout.callee
                if not isinstance(target, IRLabel) or callee is None:
                    errors.append(InvokeTargetError(caller, inst))
                    continue

                callee_layout = FunctionCallLayout(callee)
                expected_operand_count = layout.expected_operand_count
                assert expected_operand_count is not None
                if len(inst.operands) != expected_operand_count:
                    errors.append(
                        InvokeArgumentCountMismatch(
                            caller,
                            callee,
                            inst,
                            callee_layout.expected_user_arg_count,
                            int(layout.expects_hidden_fmp),
                            layout.actual_operand_count_after_target,
                        )
                    )

                arities = ret_arities[callee]

                if len(arities) == 0:
                    expected_num = 0
                elif len(arities) == 1:
                    expected_num = next(iter(arities))
                else:
                    # a function with InconsistentReturnArity, we already
                    # checked this above
                    continue

                if got_num != expected_num:
                    errors.append(InvokeArityMismatch(caller, inst, expected_num, got_num))

    return errors


def find_semantic_errors(context: IRContext) -> list[VenomError]:
    errors: list[VenomError] = []

    # Per-function basic checks (var definitions, bb termination, etc.)
    for fn in context.functions.values():
        errors.extend(find_semantic_errors_fn(fn))

    # Calling convention errors can be reported too if desired
    errors.extend(find_calling_convention_errors(context))

    return errors


def check_venom_ctx(context: IRContext):
    errors = find_semantic_errors(context)

    if errors:
        raise ExceptionGroup("venom semantic errors", errors)


def check_calling_convention(context: IRContext):
    errors = find_calling_convention_errors(context)
    if errors:
        raise ExceptionGroup("venom calling convention errors", errors)


def check_mem_ops(context: IRContext):
    for fn in context.get_functions():
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                write_op = get_memory_write_op(inst)
                read_op = get_memory_read_op(inst)
                if write_op is not None:
                    size = get_write_max_size(inst)
                    if size is not None and isinstance(write_op, IRLiteral):
                        raise CompilerPanic("Concrete memory write")  # pragma: no cover
                if read_op is not None:
                    size = get_read_size(inst)
                    if size is None or not isinstance(read_op, IRLiteral):
                        continue
                    raise CompilerPanic("Concrete memory read")  # pragma: no cover
