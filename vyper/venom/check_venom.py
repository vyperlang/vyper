from dataclasses import dataclass
from enum import Enum
from typing import Any

from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import IRAnalysesCache, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock
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


def _handle_incorrect_liveness(bb: IRBasicBlock) -> list[VenomError]:
    errors = []
    bb_defs = set()
    for inst in bb.instructions:
        if inst.output is not None:
            bb_defs.add(inst.output)

    # all variables defined in this block, plus variables from all input bbs.
    defined_vars = bb_defs.union(*(in_bb.out_vars for in_bb in bb.cfg_in))

    undef_vars = bb.instructions[-1].liveness.difference(defined_vars)

    for var in undef_vars:
        errors.append(VarNotDefined(metadata=(var, bb)))

    return errors


def check_venom_fn(fn: IRFunction) -> list[VenomError]:
    errors = []

    # check that all the bbs are terminated
    for bb in fn.get_basic_blocks():
        if not bb.is_terminated:
            errors.append(BasicBlockNotTerminated(metadata=bb))

    if errors != []:
        return errors

    ac = IRAnalysesCache(fn)
    ac.request_analysis(LivenessAnalysis)
    for bb in fn.get_basic_blocks():
        e = _handle_incorrect_liveness(bb)
        errors.extend(e)
    return errors


def check_venom_ctx(context: IRContext) -> list[VenomError]:
    errors: list[VenomError] = []

    for fn in context.functions.values():
        errors.extend(check_venom_fn(fn))

    return errors
