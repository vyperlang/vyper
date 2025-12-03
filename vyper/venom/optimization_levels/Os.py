from typing import List

from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT
from vyper.venom.optimization_levels.types import PassConfig
from vyper.venom.passes.algebraic_optimization import AlgebraicOptimizationPass
from vyper.venom.passes.assign_elimination import AssignElimination
from vyper.venom.passes.branch_optimization import BranchOptimizationPass
from vyper.venom.passes.cfg_normalization import CFGNormalization
from vyper.venom.passes.common_subexpression_elimination import CSE
from vyper.venom.passes.concretize_mem_loc import ConcretizeMemLocPass
from vyper.venom.passes.dead_store_elimination import DeadStoreElimination
from vyper.venom.passes.dft import DFTPass
from vyper.venom.passes.float_allocas import FloatAllocas
from vyper.venom.passes.literals_codesize import ReduceLiteralsCodesize
from vyper.venom.passes.load_elimination import LoadElimination
from vyper.venom.passes.lower_dload import LowerDloadPass
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.mem2var import Mem2Var
from vyper.venom.passes.memmerging import MemMergePass
from vyper.venom.passes.phi_elimination import PhiEliminationPass
from vyper.venom.passes.remove_unused_variables import RemoveUnusedVariablesPass
from vyper.venom.passes.revert_to_assert import RevertToAssert
from vyper.venom.passes.sccp.sccp import SCCP
from vyper.venom.passes.simplify_cfg import SimplifyCFGPass
from vyper.venom.passes.single_use_expansion import SingleUseExpansion

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
