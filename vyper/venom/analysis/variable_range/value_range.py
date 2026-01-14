from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from vyper.utils import SizeLimits
from vyper.venom.basicblock import IRVariable

SIGNED_MIN = SizeLimits.MIN_INT256
SIGNED_MAX = SizeLimits.MAX_INT256
UNSIGNED_MAX = SizeLimits.MAX_UINT256

# Precision threshold: ranges wider than 2^128 are widened to TOP.
# This is a performance/precision tradeoff - extremely wide ranges provide
# little optimization value and are expensive to track. Half the 256-bit
# space (2^128) is a reasonable cutoff where ranges become too imprecise.
RANGE_WIDTH_LIMIT = 1 << 128


@dataclass(frozen=True, slots=True)
class ValueRange:
    """Immutable interval representation for 256-bit modular arithmetic.

    bounds:
        None -> TOP (unknown / full range)
        (lo, hi) with lo > hi -> BOTTOM (empty / unreachable)
        Otherwise -> concrete interval [lo, hi]
    """

    bounds: Optional[tuple[int, int]] = None

    def __post_init__(self):
        # Normalize BOTTOM to canonical form (1, 0) for consistent equality
        if self.bounds is not None:
            lo, hi = self.bounds
            if lo > hi:
                object.__setattr__(self, "bounds", (1, 0))

    @property
    def lo(self) -> int:
        """Lower bound. For top ranges, returns SIGNED_MIN."""
        if self.bounds is None:
            return SIGNED_MIN
        return self.bounds[0]

    @property
    def hi(self) -> int:
        """Upper bound. For top ranges, returns UNSIGNED_MAX."""
        if self.bounds is None:
            return UNSIGNED_MAX
        return self.bounds[1]

    @classmethod
    def top(cls) -> ValueRange:
        """Create a range representing all possible values (TOP)."""
        return cls()  # bounds=None means full range

    @classmethod
    def empty(cls) -> ValueRange:
        """Create an empty range (BOTTOM)."""
        return cls((1, 0))  # lo > hi convention

    @classmethod
    def constant(cls, value: int) -> ValueRange:
        """Create a range containing a single value."""
        return cls((value, value))

    @classmethod
    def bool_range(cls) -> ValueRange:
        """Create a range for boolean values [0, 1]."""
        return cls((0, 1))

    @classmethod
    def bytes_range(cls, length: int = 1) -> ValueRange:
        """Create a range for byte values [0, 256**length - 1]."""
        if length < 0 or length > 32:
            raise ValueError("Byte length must be between 0 and 32")
        hi = (1 << (8 * length)) - 1
        return cls((0, hi))

    @property
    def is_top(self) -> bool:
        """Check if this is the top element (full range)."""
        return self.bounds is None

    @property
    def is_empty(self) -> bool:
        """Check if this is the bottom element (empty range)."""
        return self.bounds is not None and self.bounds[0] > self.bounds[1]

    @property
    def is_bottom(self) -> bool:
        """Alias for is_empty."""
        return self.is_empty

    @property
    def is_constant(self) -> bool:
        """Check if this range represents a single constant value."""
        b = self.bounds
        return b is not None and b[0] == b[1]

    def as_constant(self) -> Optional[int]:
        """Return the constant value if this is a constant range, else None."""
        if self.is_constant:
            assert self.bounds is not None
            return self.bounds[0]
        return None

    def union(self, other: ValueRange) -> ValueRange:
        """Compute the union (join) of two ranges."""
        if self.is_top or other.is_top:
            return ValueRange.top()
        if self.is_empty:
            return other
        if other.is_empty:
            return self

        assert self.bounds is not None and other.bounds is not None
        lo = min(self.bounds[0], other.bounds[0])
        hi = max(self.bounds[1], other.bounds[1])
        return ValueRange((lo, hi))

    def intersect(self, other: ValueRange) -> ValueRange:
        """Compute the intersection (meet) of two ranges."""
        if self.is_top:
            return other
        if other.is_top:
            return self
        if self.is_empty or other.is_empty:
            return ValueRange.empty()

        assert self.bounds is not None and other.bounds is not None
        lo = max(self.bounds[0], other.bounds[0])
        hi = min(self.bounds[1], other.bounds[1])
        return ValueRange((lo, hi)) if lo <= hi else ValueRange.empty()

    def clamp(self, lo: Optional[int] = None, hi: Optional[int] = None) -> ValueRange:
        """Clamp this range to the specified bounds."""
        if self.is_top:
            new_lo = SIGNED_MIN if lo is None else max(SIGNED_MIN, lo)
            new_hi = UNSIGNED_MAX if hi is None else min(UNSIGNED_MAX, hi)
        elif self.is_empty:
            return self
        else:
            assert self.bounds is not None
            new_lo = self.bounds[0] if lo is None else max(self.bounds[0], lo)
            new_hi = self.bounds[1] if hi is None else min(self.bounds[1], hi)
        return ValueRange((new_lo, new_hi))

    def __repr__(self) -> str:
        if self.is_top:
            return "TOP"
        if self.is_empty:
            return "BOTTOM"
        assert self.bounds is not None
        lo, hi = self.bounds
        if lo == hi:
            return f"{{{lo}}}"
        return f"[{lo}, {hi}]"


RangeState = dict[IRVariable, ValueRange]
