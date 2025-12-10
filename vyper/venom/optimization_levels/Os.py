# We keep thise in separate files to allow for
# easier management of different optimization levels
# and diffing between them.

from typing import List

from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT
from vyper.venom.optimization_levels.types import PassConfig
from vyper.venom.passes import (
    CSE,
    SCCP,
    AlgebraicOptimizationPass,
    AssignElimination,
    BranchOptimizationPass,
    CFGNormalization,
    ConcretizeMemLocPass,
    DeadStoreElimination,
    DFTPass,
    FloatAllocas,
    LoadElimination,
    LowerDloadPass,
    MakeSSA,
    Mem2Var,
    MemMergePass,
    PhiEliminationPass,
    ReduceLiteralsCodesize,
    RemoveUnusedVariablesPass,
    RevertToAssert,
    SimplifyCFGPass,
    SingleUseExpansion,
)

# Optimize for size
PASSES_Os: List[PassConfig] = [
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
    RemoveUnusedVariablesPass,
    (DeadStoreElimination, {"addr_space": MEMORY}),
    (DeadStoreElimination, {"addr_space": STORAGE}),
    (DeadStoreElimination, {"addr_space": TRANSIENT}),
    AssignElimination,
    RemoveUnusedVariablesPass,
    ConcretizeMemLocPass,
    SCCP,
    SimplifyCFGPass,
    # run memmerge before LowerDload
    MemMergePass,
    LowerDloadPass,
    RemoveUnusedVariablesPass,
    BranchOptimizationPass,
    AlgebraicOptimizationPass,
    # This improves the performance of cse
    RemoveUnusedVariablesPass,
    PhiEliminationPass,
    AssignElimination,
    CSE,
    AssignElimination,
    RemoveUnusedVariablesPass,
    SingleUseExpansion,
    ReduceLiteralsCodesize,
    DFTPass,
    CFGNormalization,
]
