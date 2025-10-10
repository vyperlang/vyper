from passes.assign_elimination import AssignElimination
from passes.cfg_normalization import CFGNormalization
from passes.dft import DFTPass
from passes.float_allocas import FloatAllocas
from passes.lower_dload import LowerDloadPass
from passes.make_ssa import MakeSSA
from passes.memmerging import MemMergePass
from passes.phi_elimination import PhiEliminationPass
from passes.revert_to_assert import RevertToAssert
from passes.simplify_cfg import SimplifyCFGPass
from passes.single_use_expansion import SingleUseExpansion

# No optimizations

PASSES_O0 = [
    FloatAllocas,
    SimplifyCFGPass,
    MakeSSA,
    PhiEliminationPass,
    AssignElimination,
    MakeSSA,
    PhiEliminationPass,
    AssignElimination,
    RevertToAssert,
    SimplifyCFGPass,
    MemMergePass,
    LowerDloadPass,
    PhiEliminationPass,
    AssignElimination,
    SingleUseExpansion,
    DFTPass,
    CFGNormalization,
]
