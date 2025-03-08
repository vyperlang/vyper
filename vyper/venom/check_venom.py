from dataclasses import dataclass
from enum import Enum
from typing import Any

from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import IRAnalysesCache, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction


class VenomSemanticErrorType(Enum):
    NotTerminatedBasicBlock = 1
    NotDefinedVar = 2

    def __repr__(self) -> str:
        if self == VenomSemanticErrorType.NotTerminatedBasicBlock:
            return "basic block does not terminate"
        elif self == VenomSemanticErrorType.NotDefinedVar:
            return "var not defined"
        else:
            raise CompilerPanic("unknown venom semantic error")


@dataclass
class VenomSemanticError:
    error_type: VenomSemanticErrorType
    metadata: Any


def check_venom_fn(fn: IRFunction) -> list[VenomSemanticError]:
    errors = []

    # check that all the bbs are terminated
    for bb in fn.get_basic_blocks():
        if not bb.is_terminated:
            errors.append(VenomSemanticError(VenomSemanticErrorType.NotTerminatedBasicBlock, bb))

    if errors != []:
        return errors

    ac = IRAnalysesCache(fn)
    ac.request_analysis(LivenessAnalysis)
    for bb in fn.get_basic_blocks():
        e = _handle_incorect_liveness(bb)
        errors.extend(e)
    return errors


def check_venom(context: IRContext) -> list[VenomSemanticError]:
    errors: list[VenomSemanticError] = []

    for fn in context.functions.values():
        errors.extend(check_venom_fn(fn))

    return errors


def _handle_incorrect_liveness(bb: IRBasicBlock) -> list[VenomSemanticError]:
    errors = []
    bb_defs = set()
    for inst in bb.instructions:
        if inst.output is not None:
            bb_defs.add(inst.output)

    before_live = set().union(*(in_bb.out_vars for in_bb in bb.cfg_in))

    undef_vars = bb.instructions[-1].liveness.difference(before_live.union(bb_defs))

    for var in undef_vars:
        errors.append(VenomSemanticError(VenomSemanticErrorType.NotDefinedVar, var))
    return errors
