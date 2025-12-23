"""
Range analysis for Venom IR.

This module provides flow-sensitive range analysis over Venom IR, tracking
the bounds of integer values through the control flow graph.
"""

from .analysis import VariableRangeAnalysis
from .value_range import (
    RANGE_WIDTH_LIMIT,
    SIGNED_MAX,
    SIGNED_MIN,
    UNSIGNED_MAX,
    RangeState,
    ValueRange,
)

__all__ = [
    "VariableRangeAnalysis",
    "ValueRange",
    "RangeState",
    "SIGNED_MIN",
    "SIGNED_MAX",
    "UNSIGNED_MAX",
    "RANGE_WIDTH_LIMIT",
]
