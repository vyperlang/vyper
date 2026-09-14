# We keep thise in separate files to allow for
# easier management of different optimization levels
# and diffing between them.

from typing import List

from vyper.venom.optimization_levels.types import PassConfig
from vyper.venom.passes import (
    CFGNormalization,
    ConcretizeMemLocPass,
    DFTPass,
    FmpLoweringPass,
    LowerDloadPass,
    MakeSSA,
    SimplifyCFGPass,
    SingleUseExpansion,
)

# Minimal pipeline: only the passes required to lower frontend venom to
# legal assembly. Everything here is a lowering step, not an optimization.
# This is the level used as the input to formal verification, so any pass
# added here needs a correctness (not performance) justification.
PASSES_O1: List[PassConfig] = [
    MakeSSA,
    LowerDloadPass,
    ConcretizeMemLocPass,
    FmpLoweringPass,
    # FmpLoweringPass emits a multiply-assigned FMP runner, so SSA must be
    # rebuilt afterwards (see FmpLoweringPass.required_successors)
    MakeSSA,
    # venom_to_assembly asserts that every `jmp` target is a real join point;
    # that is only guaranteed after cfg simplification
    SimplifyCFGPass,
    SingleUseExpansion,
    DFTPass,
    CFGNormalization,
]
