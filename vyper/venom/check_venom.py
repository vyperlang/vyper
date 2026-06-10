from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import DFGAnalysis, IRAnalysesCache, VarDefinition
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.call_layout import FunctionCallLayout, InvokeLayout, parse_dret_shape
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import (
    get_memory_read_op,
    get_memory_write_op,
    get_read_size,
    get_write_max_size,
)

# raw (pre-lowering) FMP opcodes; none of these may coexist with the
# lowered convention or survive FmpLoweringPass
RAW_FMP_OPS = frozenset(["dalloca", "dret", "getfmp", "setfmp", "retfmp"])


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
    message: str = "dalloca must have exactly 1 operand and 1 output"

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


class DretShapeError(VenomError):
    message: str = "dret operands are malformed"

    def __init__(self, caller: IRFunction, inst: IRInstruction, detail: str):
        self.caller = caller
        self.inst = inst
        self.detail = detail

    def __str__(self):
        bb = self.inst.parent
        return f"dret shape error in {self.caller.name}: {self.detail}\n  {self.inst}\n\n{bb}"


class DretReturnMixError(VenomError):
    message: str = "function cannot mix ret and dret"

    def __init__(self, function: IRFunction):
        self.function = function

    def __str__(self):
        return f"function {self.function.name} mixes 'ret' and 'dret'"


class DretShapeMismatch(VenomError):
    message: str = "function has inconsistent dret shape"

    def __init__(self, function: IRFunction, shapes: set[tuple[int, int]]):
        self.function = function
        self.shapes = shapes

    def __str__(self):
        return (
            f"function {self.function.name} has inconsistent 'dret' shapes: {sorted(self.shapes)}"
        )


class GetfmpArityError(VenomError):
    message: str = "getfmp must have exactly 0 operands and 1 output"

    def __init__(self, caller: IRFunction, inst: IRInstruction):
        self.caller = caller
        self.inst = inst

    def __str__(self):
        bb = self.inst.parent
        return (
            f"getfmp arity error in {self.caller.name}: "
            f"got {len(self.inst.operands)} operand(s), {self.inst.num_outputs} output(s)\n"
            f"  {self.inst}\n\n{bb}"
        )


class SetfmpArityError(VenomError):
    message: str = "setfmp must have exactly 1 operand and 0 outputs"

    def __init__(self, caller: IRFunction, inst: IRInstruction):
        self.caller = caller
        self.inst = inst

    def __str__(self):
        bb = self.inst.parent
        return (
            f"setfmp arity error in {self.caller.name}: "
            f"got {len(self.inst.operands)} operand(s), {self.inst.num_outputs} output(s)\n"
            f"  {self.inst}\n\n{bb}"
        )


class RetfmpShapeError(VenomError):
    message: str = "retfmp operands are malformed"

    def __init__(self, caller: IRFunction, inst: IRInstruction, detail: str):
        self.caller = caller
        self.inst = inst
        self.detail = detail

    def __str__(self):
        bb = self.inst.parent
        return f"retfmp shape error in {self.caller.name}: {self.detail}\n  {self.inst}\n\n{bb}"


class RetfmpReturnMixError(VenomError):
    message: str = "function cannot mix retfmp with ret or dret"

    def __init__(self, function: IRFunction):
        self.function = function

    def __str__(self):
        return f"function {self.function.name} mixes 'retfmp' with 'ret' or 'dret'"


class InitialFmpArityError(VenomError):
    message: str = "initial_fmp must have exactly 0 operands and 1 output"

    def __init__(self, caller: IRFunction, inst: IRInstruction):
        self.caller = caller
        self.inst = inst

    def __str__(self):
        bb = self.inst.parent
        return (
            f"initial_fmp arity error in {self.caller.name}: "
            f"got {len(self.inst.operands)} operand(s), {self.inst.num_outputs} output(s)\n"
            f"  {self.inst}\n\n{bb}"
        )


class ParamLayoutError(VenomError):
    message: str = "function param layout is malformed"

    def __init__(self, function: IRFunction, detail: str, inst: IRInstruction | None = None):
        self.function = function
        self.detail = detail
        self.inst = inst

    def __str__(self):
        s = f"param layout error in {self.function.name}: {self.detail}"
        if self.inst is not None:
            s += f"\n  {self.inst}"
        return s


class MixedFmpIRError(VenomError):
    message: str = "mixed raw/lowered FMP IR"

    def __init__(self, function: IRFunction, detail: str, inst: IRInstruction | None = None):
        self.function = function
        self.detail = detail
        self.inst = inst

    def __str__(self):
        s = f"mixed raw/lowered FMP IR in {self.function.name}: {self.detail}"
        if self.inst is not None:
            s += f"\n  {self.inst}"
        return s


class PostLoweringError(VenomError):
    message: str = "lowered IR violates the frozen FMP convention"

    def __init__(self, function: IRFunction, detail: str, inst: IRInstruction | None = None):
        self.function = function
        self.detail = detail
        self.inst = inst

    def __str__(self):
        s = f"post-lowering error in {self.function.name}: {self.detail}"
        if self.inst is not None:
            s += f"\n  {self.inst}"
        return s


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
                if inst.opcode in ("ret", "retfmp"):
                    # last operand is return PC; all preceding (if any) are return values
                    arities.add(len(inst.operands) - 1)
                elif inst.opcode == "dret":
                    shape = parse_dret_shape(inst)
                    if shape is not None:
                        ordinary_count, dyn_count = shape
                        arities.add(ordinary_count + dyn_count)

        ret_arities[fn] = arities

    return ret_arities


def _find_dret_errors(fn: IRFunction) -> list[VenomError]:
    errors: list[VenomError] = []
    shapes: set[tuple[int, int]] = set()
    has_ret = False
    has_dret = False
    has_retfmp = False
    layout = FunctionCallLayout(fn)

    for bb in fn.get_basic_blocks():
        for inst in bb.instructions:
            if inst.opcode == "ret":
                has_ret = True
                continue
            if inst.opcode == "retfmp":
                has_retfmp = True
                if inst.num_outputs != 0:
                    errors.append(RetfmpShapeError(fn, inst, "retfmp must not have outputs"))
                    continue
                if len(inst.operands) == 0:
                    errors.append(
                        RetfmpShapeError(fn, inst, "expected return values and return_pc")
                    )
                    continue

                # like dret, retfmp publishes the FMP to the caller, which is
                # only meaningful in internal functions with a return-PC param.
                return_pc = inst.operands[-1]
                if layout.param_for_alias(return_pc) is None:
                    errors.append(RetfmpShapeError(fn, inst, "return_pc must be a param alias"))
                continue
            if inst.opcode != "dret":
                continue

            has_dret = True
            if inst.num_outputs != 0:
                errors.append(DretShapeError(fn, inst, "dret must not have outputs"))
                continue

            shape = parse_dret_shape(inst)
            if shape is None:
                errors.append(
                    DretShapeError(
                        fn,
                        inst,
                        "expected literal dyn_count >= 1, dynamic src/size pairs, and return_pc",
                    )
                )
                continue

            # dret is valid only in internal functions with a return-PC param.
            # A static label (or any other unresolvable return_pc) must be
            # rejected: the lowered convention would otherwise conjure an FMP
            # param that pops the caller's return PC at runtime.
            return_pc = inst.operands[-1]
            if layout.param_for_alias(return_pc) is None:
                errors.append(DretShapeError(fn, inst, "return_pc must be a param alias"))
                continue

            shapes.add(shape)

    if has_ret and has_dret:
        errors.append(DretReturnMixError(fn))

    if has_retfmp and (has_ret or has_dret):
        errors.append(RetfmpReturnMixError(fn))

    if len(shapes) > 1:
        errors.append(DretShapeMismatch(fn, shapes))

    return errors


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
                    if inst.opcode not in ("ret", "dret", "retfmp") or len(inst.operands) == 0:
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


def _fn_has_raw_fmp_ops(fn: IRFunction) -> bool:
    return any(
        inst.opcode in RAW_FMP_OPS for bb in fn.get_basic_blocks() for inst in bb.instructions
    )


def _fn_has_opcode(fn: IRFunction, opcode: str) -> bool:
    return any(inst.opcode == opcode for bb in fn.get_basic_blocks() for inst in bb.instructions)


def _fn_is_fmp_lowered(fn: IRFunction) -> bool:
    """
    True if the function's FMP convention is already materialized: it
    contains lowered FMP artifacts (`bump`, an `initial_fmp` root, or a
    physical hidden FMP param) and no raw FMP opcodes.
    """
    if _fn_has_raw_fmp_ops(fn):
        return False
    return (
        _fn_has_opcode(fn, "bump")
        or _fn_has_opcode(fn, "initial_fmp")
        or FunctionCallLayout(fn).has_physical_hidden_fmp_param
    )


def _find_param_layout_errors(fn: IRFunction) -> list[VenomError]:
    errors: list[VenomError] = []

    fmp_count = 0
    retpc_count = 0
    seen_fmp = False
    seen_retpc = False
    for inst in fn.entry.instructions:
        if inst.opcode == "fmp_param":
            fmp_count += 1
            if len(inst.operands) != 0 or inst.num_outputs != 1:
                errors.append(
                    ParamLayoutError(fn, "fmp_param must have 0 operands and 1 output", inst)
                )
            if seen_retpc:
                errors.append(ParamLayoutError(fn, "fmp_param must come before retpc_param", inst))
            seen_fmp = True
        elif inst.opcode == "retpc_param":
            retpc_count += 1
            if len(inst.operands) != 0 or inst.num_outputs != 1:
                errors.append(
                    ParamLayoutError(fn, "retpc_param must have 0 operands and 1 output", inst)
                )
            seen_retpc = True
        elif inst.opcode == "param":
            if seen_fmp or seen_retpc:
                errors.append(
                    ParamLayoutError(
                        fn,
                        "plain param after fmp_param/retpc_param (canonical order is "
                        "[param*, fmp_param?, retpc_param?])",
                        inst,
                    )
                )

    if fmp_count > 1:
        errors.append(ParamLayoutError(fn, "at most one fmp_param allowed"))
    if retpc_count > 1:
        errors.append(ParamLayoutError(fn, "at most one retpc_param allowed"))

    for bb in fn.get_basic_blocks():
        if bb is fn.entry:
            continue
        for inst in bb.instructions:
            if inst.opcode in ("fmp_param", "retpc_param"):
                errors.append(
                    ParamLayoutError(fn, f"{inst.opcode} only allowed in the entry block", inst)
                )

    return errors


def _find_mixed_fmp_errors(fn: IRFunction) -> list[VenomError]:
    # raw FMP opcodes may not coexist with lowered-convention artifacts in
    # the same function: such half-lowered IR would make FmpLoweringPass
    # (the single owner of the convention) thread a function whose shape is
    # partially materialized by someone else.
    errors: list[VenomError] = []
    if not _fn_has_raw_fmp_ops(fn):
        return errors

    for inst in fn.entry.instructions:
        if inst.opcode in ("fmp_param", "retpc_param"):
            errors.append(
                MixedFmpIRError(fn, f"raw FMP opcodes coexist with `{inst.opcode}`", inst)
            )

    if _fn_has_opcode(fn, "bump"):
        errors.append(MixedFmpIRError(fn, "raw FMP opcodes coexist with lowered `bump`"))

    return errors


def find_calling_convention_errors(context: IRContext) -> list[VenomError]:
    errors: list[VenomError] = []

    # Enforce invoke binding exactly callee arity
    for fn in context.functions.values():
        errors.extend(_find_dret_errors(fn))
        errors.extend(_find_param_layout_errors(fn))
        errors.extend(_find_mixed_fmp_errors(fn))

    ret_arities = _collect_ret_arities(context)

    for fn, arities in ret_arities.items():
        errors.extend(_find_function_call_layout_errors(fn))

        if len(arities) > 1:
            errors.append(InconsistentReturnArity(fn, arities))

    for caller in context.functions.values():
        for bb in caller.get_basic_blocks():
            for inst in bb.instructions:
                got_num = inst.num_outputs
                if inst.opcode == "initial_fmp":
                    if len(inst.operands) != 0 or got_num != 1:
                        errors.append(InitialFmpArityError(caller, inst))
                    continue

                # Disallow multi-output except on invoke, bump, and dalloca.
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
                    if len(inst.operands) != 1 or got_num != 1:
                        errors.append(DallocaArityError(caller, inst))
                    continue
                if inst.opcode == "getfmp":
                    if len(inst.operands) != 0 or got_num != 1:
                        errors.append(GetfmpArityError(caller, inst))
                    continue
                if inst.opcode == "setfmp":
                    if len(inst.operands) != 1 or got_num != 0:
                        errors.append(SetfmpArityError(caller, inst))
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
                elif layout.expects_hidden_fmp and not _fn_is_fmp_lowered(caller):
                    # an invoke already carrying the hidden FMP operand is
                    # only legal in an already-lowered caller. In any other
                    # function FmpLoweringPass is the sole writer of that
                    # operand (assert-and-set): half-lowered input must be
                    # rejected here so the pass-level panic is unreachable.
                    errors.append(
                        MixedFmpIRError(
                            caller,
                            f"invoke of {callee.name} carries a hidden FMP operand "
                            "but the caller is not lowered",
                            inst,
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


def _is_fmp_rooted(
    value: IROperand, roots: set[IRVariable], dfg: DFGAnalysis, seen: set[IRVariable] | None = None
) -> bool:
    """
    Check that `value` derives from one of the function's FMP roots (the
    hidden FMP param or an `initial_fmp` instruction) through the FMP value
    grammar: assign/phi chains, `bump` outputs, hidden adopted-FMP invoke
    outputs and add/sub offsets.
    """
    if value in roots:
        return True
    if not isinstance(value, IRVariable):
        return False

    if seen is None:
        seen = set()
    if value in seen:
        # optimistic on cycles (loop-carried runners form phi/bump cycles):
        # a cycle's rootedness is determined by its loop-external inputs,
        # which the phi branch checks separately.
        return True
    seen.add(value)

    producer = dfg.get_producing_instruction(value)
    if producer is None:
        return False

    if producer.opcode == "assign" and len(producer.operands) == 1:
        return _is_fmp_rooted(producer.operands[0], roots, dfg, seen)

    if producer.opcode == "phi":
        return all(_is_fmp_rooted(op, roots, dfg, seen.copy()) for _, op in producer.phi_operands)

    if producer.opcode == "bump":
        # both outputs are FMP-derived: outputs[0] is the pre-bump FMP (the
        # allocation pointer / reclaim mark), outputs[1] the advanced FMP
        return _is_fmp_rooted(producer.operands[0], roots, dfg, seen)

    if producer.opcode in ("add", "sub"):
        # FMP values are affine offsets of the root (e.g. the desugared
        # dret pack-destination chain)
        return any(_is_fmp_rooted(op, roots, dfg, seen.copy()) for op in producer.operands)

    if producer.opcode == "invoke":
        fn = producer.parent.parent
        callee = InvokeLayout(fn.ctx, producer).callee
        if callee is None or callee._fmp_signature is None:
            return False
        outputs = producer.get_outputs()
        return callee._fmp_signature.publishes and len(outputs) > 0 and outputs[-1] == value

    return False


def _find_fmp_rootedness_errors(fn: IRFunction) -> list[VenomError]:
    errors: list[VenomError] = []

    checks: list[tuple[IRInstruction, IROperand]] = []
    for bb in fn.get_basic_blocks():
        for inst in bb.instructions:
            if inst.opcode == "bump" and len(inst.operands) == 2:
                checks.append((inst, inst.operands[0]))
            elif inst.opcode == "invoke":
                callee = InvokeLayout(fn.ctx, inst).callee
                if callee is None or callee._fmp_signature is None:
                    continue
                if callee._fmp_signature.has_fmp_param and len(inst.operands) > 1:
                    checks.append((inst, inst.operands[-1]))

    if len(checks) == 0:
        return errors

    roots: set[IRVariable] = set()
    hidden_fmp_param = FunctionCallLayout(fn).hidden_fmp_param
    if hidden_fmp_param is not None:
        roots.add(hidden_fmp_param.output)
    for bb in fn.get_basic_blocks():
        for inst in bb.instructions:
            if inst.opcode == "initial_fmp" and inst.num_outputs == 1:
                roots.add(inst.output)

    dfg = IRAnalysesCache(fn).request_analysis(DFGAnalysis)
    for inst, operand in checks:
        if not _is_fmp_rooted(operand, roots, dfg):
            what = "bump base" if inst.opcode == "bump" else "hidden invoke operand"
            errors.append(PostLoweringError(fn, f"{what} is not FMP-rooted", inst))

    return errors


def find_post_lowering_errors(context: IRContext) -> list[VenomError]:
    """
    Validate the frozen FMP calling convention after the pass pipeline:
    - no raw FMP opcode survives lowering
    - the physical param shape matches the frozen `fmp_signature`
    - invoke operand/output counts match the callee's frozen signature
    - every bump base and hidden invoke operand is FMP-rooted
    """
    errors: list[VenomError] = []

    for fn in context.functions.values():
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode in RAW_FMP_OPS:
                    errors.append(
                        PostLoweringError(fn, f"raw `{inst.opcode}` survived lowering", inst)
                    )

        sig = fn._fmp_signature
        if sig is None:
            errors.append(
                PostLoweringError(fn, "missing fmp_signature (FmpLoweringPass did not run?)")
            )
            continue

        has_param = FunctionCallLayout(fn).has_physical_hidden_fmp_param
        if has_param != sig.has_fmp_param:
            errors.append(
                PostLoweringError(
                    fn,
                    f"physical hidden-FMP param shape ({has_param}) does not match "
                    f"frozen fmp_signature ({sig.has_fmp_param})",
                )
            )

    if len(errors) > 0:
        # shape facts below assume the per-function invariants hold
        return errors

    ret_arities = _collect_ret_arities(context)

    for caller in context.functions.values():
        for bb in caller.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "invoke":
                    continue
                callee = InvokeLayout(context, inst).callee
                if callee is None:
                    continue
                callee_sig = callee._fmp_signature
                assert callee_sig is not None  # checked above

                expected_operands = (
                    1
                    + FunctionCallLayout(callee).expected_user_arg_count
                    + int(callee_sig.has_fmp_param)
                )
                if len(inst.operands) != expected_operands:
                    errors.append(
                        PostLoweringError(
                            caller,
                            f"invoke of {callee.name} expects {expected_operands} operand(s) "
                            f"per frozen signature, got {len(inst.operands)}",
                            inst,
                        )
                    )

                expected_outputs = None
                if callee._return_value_count is not None:
                    expected_outputs = callee._return_value_count + int(callee_sig.publishes)
                elif len(ret_arities[callee]) == 1:
                    # post-lowering, the hidden adopted-FMP value is part of
                    # the ret operands, so the single arity is the full
                    # output count
                    expected_outputs = next(iter(ret_arities[callee]))

                if expected_outputs is not None and inst.num_outputs != expected_outputs:
                    errors.append(
                        PostLoweringError(
                            caller,
                            f"invoke of {callee.name} expects {expected_outputs} output(s) "
                            f"per frozen signature, got {inst.num_outputs}",
                            inst,
                        )
                    )

    for fn in context.functions.values():
        errors.extend(_find_fmp_rootedness_errors(fn))

    return errors


def check_post_lowering(context: IRContext):
    errors = find_post_lowering_errors(context)
    if errors:
        raise ExceptionGroup("venom post-lowering errors", errors)


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
