from typing import List

from vyper.venom.optimization_levels.types import PassConfig
from vyper.venom.passes.assign_elimination import AssignElimination
from vyper.venom.passes.cfg_normalization import CFGNormalization
from vyper.venom.passes.dft import DFTPass
from vyper.venom.passes.float_allocas import FloatAllocas
from vyper.venom.passes.lower_dload import LowerDloadPass
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.revert_to_assert import RevertToAssert
from vyper.venom.passes.sccp.sccp import SCCP
from vyper.venom.passes.simplify_cfg import SimplifyCFGPass
from vyper.venom.passes.single_use_expansion import SingleUseExpansion

# No optimizations
PASSES_O0: List[PassConfig] = [
    FloatAllocas,
    SimplifyCFGPass,
    MakeSSA,
    SCCP,
    AssignElimination,
    RevertToAssert,
    SimplifyCFGPass,
    LowerDloadPass,
    SingleUseExpansion,
    DFTPass,
    CFGNormalization,
]
