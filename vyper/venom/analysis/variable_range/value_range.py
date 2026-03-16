from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
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


class VRangeKind(Enum):
    """
    Value range variants: Top | Bot | Iv of (int * int)
    """

    TOP = auto()
    BOT = auto()
    IV = auto()


@dataclass(frozen=True, slots=True, init=False)
class ValueRange:
    """Immutable interval representation for 256-bit modular arithmetic.

    Top | Bot | Iv of (int * int)

    - VRangeKind.TOP: unknown / full range
    - VRangeKind.BOT: empty / unreachable
    - VRangeKind.IV:  concrete interval [_lo, _hi] where _lo <= _hi

    Construction: use the factory methods top(), empty(), iv(), constant().
    The raw constructor ValueRange(IV, lo, hi) enforces lo <= hi (raises
    ValueError otherwise). The smart constructor iv(lo, hi) normalizes
    lo > hi to BOT instead of raising.
    """

    _kind: VRangeKind = VRangeKind.TOP
    _lo: int = 0
    _hi: int = 0

    def __init__(self, kind: VRangeKind = VRangeKind.TOP, lo: int = 0, hi: int = 0) -> None:
        if kind == VRangeKind.TOP:
            lo = 0
            hi = 0
        elif kind == VRangeKind.BOT:
            lo = 0
            hi = 0
        elif kind == VRangeKind.IV:
            if lo > hi:
                raise ValueError("IV requires lo <= hi; use ValueRange.iv() for smart construction")
        else:
            raise TypeError(f"invalid ValueRange kind: {kind!r}")

        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_lo", lo)
        object.__setattr__(self, "_hi", hi)

    @property
    def lo(self) -> int:
        """Lower bound. For TOP, returns SIGNED_MIN."""
        if self._kind == VRangeKind.TOP:
            return SIGNED_MIN
        return self._lo

    @property
    def hi(self) -> int:
        """Upper bound. For TOP, returns UNSIGNED_MAX."""
        if self._kind == VRangeKind.TOP:
            return UNSIGNED_MAX
        return self._hi

    @classmethod
    def top(cls) -> ValueRange:
        """Create a range representing all possible values (TOP)."""
        return cls(VRangeKind.TOP)

    @classmethod
    def empty(cls) -> ValueRange:
        """Create an empty range (BOTTOM)."""
        return cls(VRangeKind.BOT)

    @classmethod
    def iv(cls, lo: int, hi: int) -> ValueRange:
        """Create an interval [lo, hi], normalizing lo > hi to BOT.

        Unlike the raw constructor (which raises on lo > hi), this
        smart constructor treats invalid bounds as empty ranges.
        """
        if lo > hi:
            return cls(VRangeKind.BOT)
        return cls(VRangeKind.IV, lo, hi)

    @classmethod
    def constant(cls, value: int) -> ValueRange:
        """Create a range containing a single value."""
        return cls(VRangeKind.IV, value, value)

    @classmethod
    def bool_range(cls) -> ValueRange:
        """Create a range for boolean values [0, 1]."""
        return cls(VRangeKind.IV, 0, 1)

    @classmethod
    def bytes_range(cls, length: int = 1) -> ValueRange:
        """Create a range for byte values [0, 256**length - 1]."""
        if length < 0 or length > 32:
            raise ValueError("Byte length must be between 0 and 32")
        hi = (1 << (8 * length)) - 1
        return cls(VRangeKind.IV, 0, hi)

    @property
    def kind(self) -> VRangeKind:
        """The constructor tag of this range."""
        return self._kind

    @property
    def is_top(self) -> bool:
        """Check if this is the top element (full range)."""
        return self._kind == VRangeKind.TOP

    @property
    def is_empty(self) -> bool:
        """Check if this is the bottom element (empty range)."""
        return self._kind == VRangeKind.BOT

    @property
    def is_bottom(self) -> bool:
        """Alias for is_empty."""
        return self._kind == VRangeKind.BOT

    @property
    def is_constant(self) -> bool:
        """Check if this range represents a single constant value."""
        return self._kind == VRangeKind.IV and self._lo == self._hi

    def as_constant(self) -> Optional[int]:
        """Return the constant value if this is a constant range, else None."""
        if self.is_constant:
            return self._lo
        return None

    def union(self, other: ValueRange) -> ValueRange:
        """Compute the union (join) of two ranges."""
        if self._kind == VRangeKind.TOP or other._kind == VRangeKind.TOP:
            return ValueRange.top()
        if self._kind == VRangeKind.BOT:
            return other
        if other._kind == VRangeKind.BOT:
            return self

        return ValueRange.iv(min(self._lo, other._lo), max(self._hi, other._hi))

    def intersect(self, other: ValueRange) -> ValueRange:
        """Compute the intersection (meet) of two ranges."""
        if self._kind == VRangeKind.TOP:
            return other
        if other._kind == VRangeKind.TOP:
            return self
        if self._kind == VRangeKind.BOT or other._kind == VRangeKind.BOT:
            return ValueRange.empty()

        lo = max(self._lo, other._lo)
        hi = min(self._hi, other._hi)
        return ValueRange.iv(lo, hi)

    def clamp(self, lo: Optional[int] = None, hi: Optional[int] = None) -> ValueRange:
        """Clamp this range to the specified bounds."""
        if self._kind == VRangeKind.TOP:
            new_lo = SIGNED_MIN if lo is None else max(SIGNED_MIN, lo)
            new_hi = UNSIGNED_MAX if hi is None else min(UNSIGNED_MAX, hi)
        elif self._kind == VRangeKind.BOT:
            return self
        else:
            new_lo = self._lo if lo is None else max(self._lo, lo)
            new_hi = self._hi if hi is None else min(self._hi, hi)
        return ValueRange.iv(new_lo, new_hi)

    def __repr__(self) -> str:
        if self._kind == VRangeKind.TOP:
            return "TOP"
        if self._kind == VRangeKind.BOT:
            return "BOTTOM"
        if self._lo == self._hi:
            return f"{{{self._lo}}}"
        return f"[{self._lo}, {self._hi}]"


RangeState = dict[IRVariable, ValueRange]
