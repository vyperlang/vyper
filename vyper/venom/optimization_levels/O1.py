from passes.assign_elimination import AssignElimination
from passes.cfg_normalization import CFGNormalization
from passes.dead_store_elimination import DeadStoreElimination
from passes.remove_unused_variables import RemoveUnusedVariablesPass
from passes.simplify_cfg import SimplifyCFGPass
from venom.passes.algebraic_optimization import AlgebraicOptimizationPass
from venom.passes.dft import DFTPass
from venom.passes.float_allocas import FloatAllocas
from venom.passes.lower_dload import LowerDloadPass
from venom.passes.make_ssa import MakeSSA
from venom.passes.memmerging import MemMergePass
from venom.passes.phi_elimination import PhiEliminationPass
from venom.passes.revert_to_assert import RevertToAssert
from venom.passes.sccp.sccp import SCCP
from venom.passes.single_use_expansion import SingleUseExpansion

from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT

# Basic optimizations

PASSES_O1 = [
    FloatAllocas,
    SimplifyCFGPass,
    MakeSSA,
    PhiEliminationPass,
    AlgebraicOptimizationPass,
    (SCCP, {"remove_allocas": False}),
    SimplifyCFGPass,
    AssignElimination,
    MakeSSA,
    PhiEliminationPass,
    SCCP,
    SimplifyCFGPass,
    AssignElimination,
    AlgebraicOptimizationPass,
    SCCP,
    AssignElimination,
    RevertToAssert,
    SimplifyCFGPass,
    MemMergePass,
    RemoveUnusedVariablesPass,
    (DeadStoreElimination, {"addr_space": MEMORY}),
    (DeadStoreElimination, {"addr_space": STORAGE}),
    (DeadStoreElimination, {"addr_space": TRANSIENT}),
    LowerDloadPass,
    AlgebraicOptimizationPass,
    RemoveUnusedVariablesPass,
    PhiEliminationPass,
    AssignElimination,
    RemoveUnusedVariablesPass,
    SingleUseExpansion,
    DFTPass,
    CFGNormalization,
]
