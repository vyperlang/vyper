from passes.algebraic_optimization import AlgebraicOptimizationPass
from passes.assign_elimination import AssignElimination
from passes.branch_optimization import BranchOptimizationPass
from passes.cfg_normalization import CFGNormalization
from passes.common_subexpression_elimination import CSE
from passes.dead_store_elimination import DeadStoreElimination
from passes.dft import DFTPass
from passes.float_allocas import FloatAllocas
from passes.load_elimination import LoadElimination
from passes.lower_dload import LowerDloadPass
from passes.make_ssa import MakeSSA
from passes.mem2var import Mem2Var
from passes.memmerging import MemMergePass
from passes.phi_elimination import PhiEliminationPass
from passes.remove_unused_variables import RemoveUnusedVariablesPass
from passes.revert_to_assert import RevertToAssert
from passes.sccp.sccp import SCCP
from passes.simplify_cfg import SimplifyCFGPass
from passes.single_use_expansion import SingleUseExpansion

from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT

# Aggressive optimizations

PASSES_O3 = [
    FloatAllocas,
    SimplifyCFGPass,
    MakeSSA,
    PhiEliminationPass,
    AlgebraicOptimizationPass,
    (SCCP, {"remove_allocas": False}),
    SimplifyCFGPass,
    AssignElimination,
    Mem2Var,
    MakeSSA,
    PhiEliminationPass,
    SCCP,
    SimplifyCFGPass,
    AssignElimination,
    AlgebraicOptimizationPass,
    LoadElimination,
    PhiEliminationPass,
    AssignElimination,
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
    BranchOptimizationPass,
    AlgebraicOptimizationPass,
    RemoveUnusedVariablesPass,
    PhiEliminationPass,
    AssignElimination,
    CSE,
    AssignElimination,
    RemoveUnusedVariablesPass,
    SingleUseExpansion,
    DFTPass,
    CFGNormalization,
]
