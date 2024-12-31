from dataclasses import dataclass
from typing import Optional

from vyper.compiler.settings import OptimizationLevel, Settings


@dataclass
class VenomSettings:
    optimize: Optional[OptimizationLevel] = None
    evm_version: Optional[str] = None
    debug: Optional[bool] = None

    @classmethod
    def from_vyper_settings(cls, settings: Settings):
        return cls(
            optimize=settings.optimize, evm_version=settings.evm_version, debug=settings.debug
        )

    @classmethod
    def from_optimization_level(cls, optimize: OptimizationLevel):
        return cls(optimize=optimize, debug=False)
