from typing import List

from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT
from vyper.venom.optimization_levels.types import PassConfig
from vyper.venom.passes.algebraic_optimization import AlgebraicOptimizationPass
from vyper.venom.passes.assign_elimination import AssignElimination
from vyper.venom.passes.branch_optimization import BranchOptimizationPass
from vyper.venom.passes.cfg_normalization import CFGNormalization
from vyper.venom.passes.dead_store_elimination import DeadStoreElimination
from vyper.venom.passes.dft import DFTPass
from vyper.venom.passes.float_allocas import FloatAllocas
from vyper.venom.passes.lower_dload import LowerDloadPass
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.memmerging import MemMergePass
from vyper.venom.passes.phi_elimination import PhiEliminationPass
from vyper.venom.passes.remove_unused_variables import RemoveUnusedVariablesPass
from vyper.venom.passes.revert_to_assert import RevertToAssert
from vyper.venom.passes.sccp.sccp import SCCP
from vyper.venom.passes.simplify_cfg import SimplifyCFGPass
from vyper.venom.passes.single_use_expansion import SingleUseExpansion

# Basic optimizations
PASSES_O1: List[PassConfig] = [
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
    BranchOptimizationPass,
    AlgebraicOptimizationPass,
    RemoveUnusedVariablesPass,
    PhiEliminationPass,
    AssignElimination,
    RemoveUnusedVariablesPass,
    SingleUseExpansion,
    DFTPass,
    CFGNormalization,
]
