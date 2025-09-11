from vyper.venom.analysis import IRAnalysesCache, VarDefinition
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction


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


class MultiOutputNonInvoke(VenomError):
    message: str = "multi-output assignment only supported for invoke"

    def __init__(self, caller: IRFunction, inst: IRInstruction):
        self.caller = caller
        self.inst = inst

    def __str__(self):
        bb = self.inst.parent
        return f"multi-output on non-invoke in {self.caller.name}:\n" f"  {self.inst}\n\n{bb}"


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


def _collect_ret_arities(context: IRContext) -> dict[IRFunction, int] | dict:
    ret_arities: dict[IRFunction, int] = {}
    for fn in context.functions.values():
        arities: set[int] = set()
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "ret":
                    # last operand is return PC; all preceding (if any) are return values
                    arity = max(0, len(inst.operands) - 1)
                    arities.add(arity)
        if len(arities) == 1:
            ret_arities[fn] = next(iter(arities))
        elif len(arities) == 0:
            ret_arities[fn] = 0
    return ret_arities


def find_calling_convention_errors(context: IRContext) -> list[VenomError]:
    errors: list[VenomError] = []

    # Enforce fixed-arity returns per function (by 'ret' sites)
    for fn in context.functions.values():
        arities: set[int] = set()
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "ret":
                    arity = max(0, len(inst.operands) - 1)
                    arities.add(arity)
        if len(arities) > 1:
            errors.append(InconsistentReturnArity(fn, arities))

    # Enforce invoke binding exactly callee arity
    ret_arities = _collect_ret_arities(context)
    for caller in context.functions.values():
        for bb in caller.get_basic_blocks():
            for inst in bb.instructions:
                # Disallow multi-output except on invoke
                if len(inst.get_outputs()) > 1 and inst.opcode != "invoke":
                    errors.append(MultiOutputNonInvoke(caller, inst))
                    continue
                if inst.opcode != "invoke":
                    continue
                target = inst.operands[0]
                if not isinstance(target, IRLabel):
                    continue
                try:
                    callee = context.get_function(target)
                except Exception:
                    continue
                expected = ret_arities.get(callee, 0)
                got = len(inst.get_outputs())
                if got != expected:
                    errors.append(InvokeArityMismatch(caller, inst, expected, got))

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
