# TODO: O1 (minimal passes) is currently disabled because it can cause
# "stack too deep" errors. Re-enable once stack spilling machinery is
# implemented to allow compilation with minimal optimization passes.
# from vyper.venom.optimization_levels.O1 import PASSES_O1
from vyper.venom.optimization_levels.O2 import PASSES_O2
from vyper.venom.optimization_levels.O3 import PASSES_O3
from vyper.venom.optimization_levels.Os import PASSES_Os

__all__ = ["PASSES_O2", "PASSES_O3", "PASSES_Os"]
