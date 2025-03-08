from typing import Any, Sequence

from vyper.venom.analysis import IRAnalysesCache, VarDefinition
from vyper.venom.basicblock import IRBasicBlock, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction


class VenomError(Exception):
    message: str
    metadata: Any

    def __init__(self, metadata):
        self.metadata = metadata

    def __str__(self):
        return f"{self.message}\n\n{self.metadata}"


class BasicBlockNotTerminated(VenomError):
    message: str = "basic block does not terminate"


class VarNotDefined(VenomError):
    message: str = "variable is used before definition"


def _handle_var_definition(bb: IRBasicBlock, var_def: VarDefinition) -> list[VenomError]:
    errors = []
    for inst in bb.instructions:
        defined = var_def.defined_vars[inst]
        for op in inst.operands:
            if isinstance(op, IRVariable):
                if op not in defined:
                    errors.append(VarNotDefined(metadata=(op, bb)))
    return errors


def find_semantic_errors_fn(fn: IRFunction) -> Sequence[VenomError]:
    errors: list[VenomError] = []

    # check that all the bbs are terminated
    for bb in fn.get_basic_blocks():
        if not bb.is_terminated:
            errors.append(BasicBlockNotTerminated(metadata=bb))

    if len(errors) > 0:
        return errors

    ac = IRAnalysesCache(fn)
    var_def: VarDefinition = ac.request_analysis(VarDefinition)  # type: ignore
    for bb in fn.get_basic_blocks():
        e = _handle_var_definition(bb, var_def)
        errors.extend(e)
    return errors


def find_semantic_errors(context: IRContext) -> Sequence[VenomError]:
    errors: list[VenomError] = []

    for fn in context.functions.values():
        errors.extend(find_semantic_errors_fn(fn))

    return errors


def check_venom_ctx(context: IRContext):
    errors = find_semantic_errors(context)

    if errors:
        raise ExceptionGroup("venom semantic errors", errors)
