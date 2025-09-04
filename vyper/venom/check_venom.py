from vyper.venom.analysis import IRAnalysesCache, VarDefinition
from vyper.venom.basicblock import IRBasicBlock, IRVariable
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


def find_semantic_errors(context: IRContext) -> list[VenomError]:
    errors: list[VenomError] = []

    for fn in context.functions.values():
        errors.extend(find_semantic_errors_fn(fn))

    return errors


def check_venom_ctx(context: IRContext):
    errors = find_semantic_errors(context)

    if errors:
        raise ExceptionGroup("venom semantic errors", errors)
