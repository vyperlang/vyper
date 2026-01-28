"""Property-based tests for variable range analysis.

This module provides infrastructure for testing the soundness and correctness
of range analysis using hypothesis-based property testing. The key invariant
is that any value the EVM can produce at runtime must be contained within
the range computed by the analysis.
"""

from __future__ import annotations

from typing import Callable

from hypothesis import given, settings
from hypothesis import strategies as st

from vyper.utils import wrap256
from vyper.venom.analysis.variable_range.evaluators import (
    _eval_add,
    _eval_and,
    _eval_byte,
    _eval_compare,
    _eval_div,
    _eval_eq,
    _eval_iszero,
    _eval_mod,
    _eval_mul,
    _eval_not,
    _eval_or,
    _eval_sar,
    _eval_shl,
    _eval_shr,
    _eval_signextend,
    _eval_sub,
    _eval_xor,
)
from vyper.venom.analysis.variable_range.value_range import (
    SIGNED_MAX,
    SIGNED_MIN,
    UNSIGNED_MAX,
    ValueRange,
)
from vyper.venom.basicblock import IRInstruction, IRLiteral, IRVariable

# =============================================================================
# CONSTANTS
# =============================================================================

UINT256_MAX = UNSIGNED_MAX
UINT256_MIN = 0
INT256_MAX = SIGNED_MAX
INT256_MIN = SIGNED_MIN

# =============================================================================
# HYPOTHESIS STRATEGIES
# =============================================================================

# Full 256-bit unsigned integer strategy
uint256_strategy = st.integers(min_value=0, max_value=UINT256_MAX)

# Full 256-bit signed integer strategy
int256_strategy = st.integers(min_value=INT256_MIN, max_value=INT256_MAX)

# Small unsigned integers for faster tests
small_uint_strategy = st.integers(min_value=0, max_value=2**64)

# Small signed integers for faster tests
small_int_strategy = st.integers(min_value=-(2**63), max_value=2**63 - 1)

# Byte values [0, 255]
byte_strategy = st.integers(min_value=0, max_value=255)

# Boolean strategy (0 or 1)
bool_strategy = st.integers(min_value=0, max_value=1)

# Shift amount strategy (0 to 256 for edge case testing)
shift_strategy = st.integers(min_value=0, max_value=256)


@st.composite
def value_range_strategy(draw: st.DrawFn, allow_empty: bool = False) -> ValueRange:
    """Generate valid ValueRange objects.

    Args:
        draw: Hypothesis draw function
        allow_empty: Whether to allow empty (bottom) ranges

    Returns:
        A valid ValueRange object
    """
    # Choose range type
    range_type = draw(
        st.sampled_from(["top", "constant", "range"] + (["empty"] if allow_empty else []))
    )

    if range_type == "top":
        return ValueRange.top()
    elif range_type == "empty":
        return ValueRange.empty()
    elif range_type == "constant":
        # Use smaller values more often for faster tests
        val = draw(st.one_of(small_int_strategy, int256_strategy))
        return ValueRange.constant(val)
    else:
        # Generate a range [lo, hi] where lo <= hi
        lo = draw(int256_strategy)
        hi = draw(int256_strategy)
        if lo > hi:
            lo, hi = hi, lo
        return ValueRange((lo, hi))


@st.composite
def nonnegative_range_strategy(draw: st.DrawFn) -> ValueRange:
    """Generate ValueRange objects that are non-negative."""
    range_type = draw(st.sampled_from(["top", "constant", "range"]))

    if range_type == "top":
        # For non-negative, use [0, UINT256_MAX]
        return ValueRange((0, UINT256_MAX))
    elif range_type == "constant":
        val = draw(uint256_strategy)
        return ValueRange.constant(val)
    else:
        lo = draw(uint256_strategy)
        hi = draw(uint256_strategy)
        if lo > hi:
            lo, hi = hi, lo
        return ValueRange((lo, hi))


@st.composite
def signed_byte_range_strategy(draw: st.DrawFn, byte_width: int = 1) -> ValueRange:
    """Generate ValueRange for signextend target range.

    Args:
        draw: Hypothesis draw function
        byte_width: Number of bytes (1-32)
    """
    bits = 8 * byte_width
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1
    val = draw(st.integers(min_value=lo, max_value=hi))
    return ValueRange.constant(val)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def wrap256_unsigned(val: int) -> int:
    """Wrap value to unsigned 256-bit representation.

    Args:
        val: Any integer value

    Returns:
        Value wrapped to [0, 2^256 - 1]
    """
    return wrap256(val)


def wrap256_signed(val: int) -> int:
    """Wrap value to signed 256-bit representation.

    Args:
        val: Any integer value

    Returns:
        Value wrapped to [-2^255, 2^255 - 1]
    """
    return wrap256(val, signed=True)


def to_signed(val: int) -> int:
    """Convert unsigned 256-bit value to signed interpretation.

    Args:
        val: Unsigned value in [0, 2^256 - 1]

    Returns:
        Signed interpretation in [-2^255, 2^255 - 1]
    """
    if val > INT256_MAX:
        return val - (UINT256_MAX + 1)
    return val


def to_unsigned(val: int) -> int:
    """Convert signed 256-bit value to unsigned interpretation.

    Args:
        val: Signed value in [-2^255, 2^255 - 1]

    Returns:
        Unsigned interpretation in [0, 2^256 - 1]
    """
    if val < 0:
        return val + (UINT256_MAX + 1)
    return val


def value_in_range(val: int, rng: ValueRange) -> bool:
    """Check if an unsigned value is contained in a range.

    The value is first converted to signed representation to match
    the range's signed bounds.

    Args:
        val: Unsigned 256-bit value
        rng: ValueRange to check against

    Returns:
        True if the value is in the range
    """
    if rng.is_top:
        return True
    if rng.is_empty:
        return False

    # Convert to signed for comparison with signed bounds
    signed_val = to_signed(val)
    return rng.lo <= signed_val <= rng.hi


def value_in_range_signed(val: int, rng: ValueRange) -> bool:
    """Check if a signed value is contained in a range.

    Args:
        val: Signed 256-bit value
        rng: ValueRange to check against

    Returns:
        True if the value is in the range
    """
    if rng.is_top:
        return True
    if rng.is_empty:
        return False
    return rng.lo <= val <= rng.hi


# =============================================================================
# EVM OPERATION EVALUATORS
# =============================================================================


def eval_evm_add(a: int, b: int) -> int:
    """Evaluate EVM ADD operation."""
    return wrap256_unsigned((a + b) % (UINT256_MAX + 1))


def eval_evm_sub(a: int, b: int) -> int:
    """Evaluate EVM SUB operation."""
    return wrap256_unsigned((a - b) % (UINT256_MAX + 1))


def eval_evm_mul(a: int, b: int) -> int:
    """Evaluate EVM MUL operation."""
    return wrap256_unsigned((a * b) % (UINT256_MAX + 1))


def eval_evm_div(a: int, b: int) -> int:
    """Evaluate EVM DIV operation (unsigned)."""
    if b == 0:
        return 0
    return a // b


def eval_evm_mod(a: int, b: int) -> int:
    """Evaluate EVM MOD operation (unsigned)."""
    if b == 0:
        return 0
    return a % b


def eval_evm_sdiv(a: int, b: int) -> int:
    """Evaluate EVM SDIV operation (signed)."""
    if b == 0:
        return 0
    a_signed = to_signed(a)
    b_signed = to_signed(b)
    # Handle special case: min_int / -1 = min_int in EVM
    if a_signed == INT256_MIN and b_signed == -1:
        return to_unsigned(INT256_MIN)
    result = abs(a_signed) // abs(b_signed)
    if (a_signed < 0) != (b_signed < 0):
        result = -result
    return to_unsigned(result)


def eval_evm_smod(a: int, b: int) -> int:
    """Evaluate EVM SMOD operation (signed)."""
    if b == 0:
        return 0
    a_signed = to_signed(a)
    b_signed = to_signed(b)
    result = abs(a_signed) % abs(b_signed)
    if a_signed < 0:
        result = -result
    return to_unsigned(result)


def eval_evm_and(a: int, b: int) -> int:
    """Evaluate EVM AND operation."""
    return a & b


def eval_evm_or(a: int, b: int) -> int:
    """Evaluate EVM OR operation."""
    return a | b


def eval_evm_xor(a: int, b: int) -> int:
    """Evaluate EVM XOR operation."""
    return a ^ b


def eval_evm_not(a: int) -> int:
    """Evaluate EVM NOT operation."""
    return UINT256_MAX ^ a


def eval_evm_byte(i: int, x: int) -> int:
    """Evaluate EVM BYTE operation."""
    if i >= 32:
        return 0
    return (x >> (248 - i * 8)) & 0xFF


def eval_evm_shl(shift: int, value: int) -> int:
    """Evaluate EVM SHL operation."""
    if shift >= 256:
        return 0
    return (value << shift) & UINT256_MAX


def eval_evm_shr(shift: int, value: int) -> int:
    """Evaluate EVM SHR operation."""
    if shift >= 256:
        return 0
    return value >> shift


def eval_evm_sar(shift: int, value: int) -> int:
    """Evaluate EVM SAR operation (arithmetic shift right)."""
    if shift >= 256:
        # Result is 0 if positive, -1 (all 1s) if negative
        signed_val = to_signed(value)
        if signed_val < 0:
            return UINT256_MAX  # -1 in unsigned
        return 0
    signed_val = to_signed(value)
    result = signed_val >> shift
    return to_unsigned(result)


def eval_evm_signextend(b: int, x: int) -> int:
    """Evaluate EVM SIGNEXTEND operation.

    SIGNEXTEND(b, x) sign-extends x from (b+1) bytes.
    """
    if b >= 31:
        return x
    # b is the byte index (0-30), so we're sign-extending from (b+1) bytes
    bits = 8 * (b + 1)
    sign_bit = 1 << (bits - 1)
    mask = (1 << bits) - 1
    low_bits = x & mask
    if low_bits & sign_bit:
        # Sign bit is set, extend with 1s
        return low_bits | (UINT256_MAX ^ mask)
    else:
        return low_bits


def eval_evm_lt(a: int, b: int) -> int:
    """Evaluate EVM LT operation (unsigned)."""
    return 1 if a < b else 0


def eval_evm_gt(a: int, b: int) -> int:
    """Evaluate EVM GT operation (unsigned)."""
    return 1 if a > b else 0


def eval_evm_slt(a: int, b: int) -> int:
    """Evaluate EVM SLT operation (signed)."""
    return 1 if to_signed(a) < to_signed(b) else 0


def eval_evm_sgt(a: int, b: int) -> int:
    """Evaluate EVM SGT operation (signed)."""
    return 1 if to_signed(a) > to_signed(b) else 0


def eval_evm_eq(a: int, b: int) -> int:
    """Evaluate EVM EQ operation."""
    return 1 if a == b else 0


def eval_evm_iszero(a: int) -> int:
    """Evaluate EVM ISZERO operation."""
    return 1 if a == 0 else 0


def eval_evm_op(opcode: str, *args: int) -> int:
    """Evaluate an EVM opcode on concrete values.

    All values are in unsigned 256-bit representation.

    Args:
        opcode: The EVM opcode name
        *args: Operand values (in stack order, last pushed = first arg)

    Returns:
        The result of the operation in unsigned 256-bit representation
    """
    dispatch: dict[str, Callable[..., int]] = {
        "add": eval_evm_add,
        "sub": eval_evm_sub,
        "mul": eval_evm_mul,
        "div": eval_evm_div,
        "mod": eval_evm_mod,
        "sdiv": eval_evm_sdiv,
        "smod": eval_evm_smod,
        "and": eval_evm_and,
        "or": eval_evm_or,
        "xor": eval_evm_xor,
        "not": eval_evm_not,
        "byte": eval_evm_byte,
        "shl": eval_evm_shl,
        "shr": eval_evm_shr,
        "sar": eval_evm_sar,
        "signextend": eval_evm_signextend,
        "lt": eval_evm_lt,
        "gt": eval_evm_gt,
        "slt": eval_evm_slt,
        "sgt": eval_evm_sgt,
        "eq": eval_evm_eq,
        "iszero": eval_evm_iszero,
    }

    if opcode not in dispatch:
        raise ValueError(f"Unknown opcode: {opcode}")

    return dispatch[opcode](*args)


# =============================================================================
# TEST CONFIGURATION
# =============================================================================

# Default hypothesis settings for CI (no deadline to avoid flakiness)
ci_settings = settings(deadline=None, max_examples=100)

# Fast settings for quick iteration
fast_settings = settings(deadline=None, max_examples=20)

# Thorough settings for comprehensive testing
thorough_settings = settings(deadline=None, max_examples=500)


# =============================================================================
# BASIC INFRASTRUCTURE TESTS
# =============================================================================


class TestValueRangeBasics:
    """Tests for basic ValueRange operations."""

    @given(value_range_strategy())
    @settings(deadline=None)
    def test_top_is_absorbing_for_union(self, rng: ValueRange) -> None:
        """TOP union anything = TOP."""
        result = ValueRange.top().union(rng)
        assert result.is_top

    @given(value_range_strategy())
    @settings(deadline=None)
    def test_top_is_identity_for_intersect(self, rng: ValueRange) -> None:
        """TOP intersect anything = anything."""
        result = ValueRange.top().intersect(rng)
        # Result should be equivalent to rng
        if rng.is_top:
            assert result.is_top
        elif rng.is_empty:
            assert result.is_empty
        else:
            assert result.bounds == rng.bounds

    @given(value_range_strategy())
    @settings(deadline=None)
    def test_empty_is_identity_for_union(self, rng: ValueRange) -> None:
        """EMPTY union anything = anything."""
        result = ValueRange.empty().union(rng)
        if rng.is_top:
            assert result.is_top
        elif rng.is_empty:
            assert result.is_empty
        else:
            assert result.bounds == rng.bounds

    @given(value_range_strategy())
    @settings(deadline=None)
    def test_empty_is_absorbing_for_intersect(self, rng: ValueRange) -> None:
        """EMPTY intersect anything = EMPTY."""
        result = ValueRange.empty().intersect(rng)
        assert result.is_empty

    def test_bottom_canonical_representation(self) -> None:
        """All BOTTOM representations should be equal (canonical form)."""
        # Different ways to create BOTTOM (lo > hi)
        bottom1 = ValueRange((1, 0))
        bottom2 = ValueRange((2, 1))
        bottom3 = ValueRange((100, 0))
        bottom4 = ValueRange.empty()

        # All should be equal due to canonical normalization
        assert bottom1 == bottom2
        assert bottom2 == bottom3
        assert bottom3 == bottom4
        assert bottom1 == bottom4

        # All should have canonical bounds (1, 0)
        assert bottom1.bounds == (1, 0)
        assert bottom2.bounds == (1, 0)
        assert bottom3.bounds == (1, 0)
        assert bottom4.bounds == (1, 0)

    @given(int256_strategy)
    @settings(deadline=None)
    def test_constant_range_contains_value(self, val: int) -> None:
        """A constant range contains exactly its value."""
        rng = ValueRange.constant(val)
        assert rng.is_constant
        assert rng.lo == val
        assert rng.hi == val


class TestHelperFunctions:
    """Tests for helper functions."""

    @given(uint256_strategy)
    @settings(deadline=None)
    def test_to_signed_roundtrip(self, val: int) -> None:
        """to_signed and to_unsigned are inverses."""
        signed = to_signed(val)
        back = to_unsigned(signed)
        assert back == val

    @given(int256_strategy)
    @settings(deadline=None)
    def test_to_unsigned_roundtrip(self, val: int) -> None:
        """to_unsigned and to_signed are inverses."""
        unsigned = to_unsigned(val)
        back = to_signed(unsigned)
        assert back == val

    @given(uint256_strategy)
    @settings(deadline=None)
    def test_wrap256_unsigned_idempotent(self, val: int) -> None:
        """wrap256 on valid unsigned values is identity."""
        assert wrap256_unsigned(val) == val

    @given(int256_strategy)
    @settings(deadline=None)
    def test_wrap256_signed_roundtrip(self, val: int) -> None:
        """wrap256 signed roundtrip preserves value."""
        unsigned = to_unsigned(val)
        wrapped = wrap256_signed(unsigned)
        assert wrapped == val


class TestEVMOperations:
    """Tests for EVM operation evaluation."""

    @given(small_uint_strategy, small_uint_strategy)
    @settings(deadline=None)
    def test_add_commutative(self, a: int, b: int) -> None:
        """ADD is commutative."""
        assert eval_evm_add(a, b) == eval_evm_add(b, a)

    @given(small_uint_strategy, small_uint_strategy)
    @settings(deadline=None)
    def test_mul_commutative(self, a: int, b: int) -> None:
        """MUL is commutative."""
        assert eval_evm_mul(a, b) == eval_evm_mul(b, a)

    @given(small_uint_strategy)
    @settings(deadline=None)
    def test_add_zero_identity(self, a: int) -> None:
        """ADD with zero is identity."""
        assert eval_evm_add(a, 0) == a

    @given(small_uint_strategy)
    @settings(deadline=None)
    def test_mul_one_identity(self, a: int) -> None:
        """MUL with one is identity."""
        assert eval_evm_mul(a, 1) == a

    @given(small_uint_strategy)
    @settings(deadline=None)
    def test_mul_zero_absorbing(self, a: int) -> None:
        """MUL with zero gives zero."""
        assert eval_evm_mul(a, 0) == 0

    @given(uint256_strategy)
    @settings(deadline=None)
    def test_iszero_boolean_result(self, a: int) -> None:
        """ISZERO always returns 0 or 1."""
        result = eval_evm_iszero(a)
        assert result in (0, 1)

    @given(byte_strategy, uint256_strategy)
    @settings(deadline=None)
    def test_byte_bounded(self, i: int, x: int) -> None:
        """BYTE always returns value in [0, 255]."""
        result = eval_evm_byte(i, x)
        assert 0 <= result <= 255

    @given(st.integers(min_value=0, max_value=30), uint256_strategy)
    @settings(deadline=None)
    def test_signextend_range(self, b: int, x: int) -> None:
        """SIGNEXTEND result is in expected signed range."""
        result = eval_evm_signextend(b, x)
        signed_result = to_signed(result)
        bits = 8 * (b + 1)
        lo = -(1 << (bits - 1))
        hi = (1 << (bits - 1)) - 1
        assert lo <= signed_result <= hi


# =============================================================================
# MOCK INSTRUCTION HELPERS
# =============================================================================


def make_inst(opcode: str, *operands) -> IRInstruction:
    """Create a mock IR instruction for testing evaluators.

    Note: We don't set output as evaluators only use operands.
    """
    ops = []
    for op in operands:
        if isinstance(op, int):
            ops.append(IRLiteral(op))
        elif isinstance(op, (IRVariable, IRLiteral)):
            ops.append(op)
        else:
            ops.append(op)
    return IRInstruction(opcode, ops)


def make_state(*var_ranges) -> dict:
    """Create a state dictionary from (variable, range) pairs."""
    return {var: rng for var, rng in var_ranges}


# =============================================================================
# SOUNDNESS TESTS: ARITHMETIC OPERATIONS
# =============================================================================


class TestArithmeticSoundness:
    """Property tests verifying arithmetic evaluator soundness."""

    @given(a=small_uint_strategy, b=small_uint_strategy)
    @settings(deadline=None, max_examples=200)
    def test_add_soundness_constants(self, a: int, b: int) -> None:
        """ADD with constant inputs: result must be in computed range."""
        inst = make_inst("add", a, b)
        result_range = _eval_add(inst, {})
        actual = eval_evm_add(a, b)
        assert value_in_range(
            actual, result_range
        ), f"ADD unsound: {a} + {b} = {actual}, range = {result_range}"

    @given(a=small_uint_strategy, b=small_uint_strategy)
    @settings(deadline=None, max_examples=200)
    def test_sub_soundness_constants(self, a: int, b: int) -> None:
        """SUB with constant inputs: result must be in computed range."""
        # Evaluator reads operands[-1] as lhs, operands[-2] as rhs
        inst = make_inst("sub", b, a)
        result_range = _eval_sub(inst, {})
        actual = eval_evm_sub(a, b)
        assert value_in_range(
            actual, result_range
        ), f"SUB unsound: {a} - {b} = {actual}, range = {result_range}"

    @given(a=small_uint_strategy, b=small_uint_strategy)
    @settings(deadline=None, max_examples=200)
    def test_mul_soundness_constants(self, a: int, b: int) -> None:
        """MUL with constant inputs: result must be in computed range."""
        inst = make_inst("mul", a, b)
        result_range = _eval_mul(inst, {})
        actual = eval_evm_mul(a, b)
        assert value_in_range(
            actual, result_range
        ), f"MUL unsound: {a} * {b} = {actual}, range = {result_range}"

    @given(a=small_uint_strategy, b=small_uint_strategy)
    @settings(deadline=None, max_examples=200)
    def test_div_soundness_constants(self, a: int, b: int) -> None:
        """DIV with constant inputs: result must be in computed range."""
        # Evaluator reads operands[-1] as dividend, operands[-2] as divisor
        inst = make_inst("div", b, a)
        result_range = _eval_div(inst, {})
        actual = eval_evm_div(a, b)
        assert value_in_range(
            actual, result_range
        ), f"DIV unsound: {a} / {b} = {actual}, range = {result_range}"

    @given(a=small_uint_strategy, b=small_uint_strategy)
    @settings(deadline=None, max_examples=200)
    def test_mod_soundness_constants(self, a: int, b: int) -> None:
        """MOD with constant inputs: result must be in computed range."""
        # Evaluator reads operands[-2] as divisor
        inst = make_inst("mod", b, a)
        result_range = _eval_mod(inst, {})
        actual = eval_evm_mod(a, b)
        assert value_in_range(
            actual, result_range
        ), f"MOD unsound: {a} % {b} = {actual}, range = {result_range}"

    def test_div_by_zero_returns_zero(self) -> None:
        """DIV by zero must return 0 (EVM spec)."""
        # Evaluator reads operands[-1] as dividend, operands[-2] as divisor
        inst = make_inst("div", 0, 12345)
        result_range = _eval_div(inst, {})
        assert value_in_range(0, result_range)

    def test_mod_by_zero_returns_zero(self) -> None:
        """MOD by zero must return 0 (EVM spec)."""
        # Evaluator reads operands[-2] as divisor
        inst = make_inst("mod", 0, 12345)
        result_range = _eval_mod(inst, {})
        assert value_in_range(0, result_range)


# =============================================================================
# SOUNDNESS TESTS: COMPARISON OPERATIONS
# =============================================================================


class TestComparisonSoundness:
    """Property tests verifying comparison evaluator soundness."""

    @given(a=int256_strategy, b=int256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_lt_soundness(self, a: int, b: int) -> None:
        """LT (unsigned): result must be in computed range."""
        var_a = IRVariable("%a")
        var_b = IRVariable("%b")
        # Evaluator reads operands[-1] as lhs, operands[-2] as rhs
        inst = make_inst("lt", var_b, var_a)
        state = {var_a: ValueRange.constant(a), var_b: ValueRange.constant(b)}
        result_range = _eval_compare(inst, state)
        # EVM lt is unsigned
        actual = eval_evm_lt(to_unsigned(a), to_unsigned(b))
        assert value_in_range(
            actual, result_range
        ), f"LT unsound: lt({a}, {b}) = {actual}, range = {result_range}"

    @given(a=int256_strategy, b=int256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_gt_soundness(self, a: int, b: int) -> None:
        """GT (unsigned): result must be in computed range."""
        var_a = IRVariable("%a")
        var_b = IRVariable("%b")
        # Evaluator reads operands[-1] as lhs, operands[-2] as rhs
        inst = make_inst("gt", var_b, var_a)
        state = {var_a: ValueRange.constant(a), var_b: ValueRange.constant(b)}
        result_range = _eval_compare(inst, state)
        actual = eval_evm_gt(to_unsigned(a), to_unsigned(b))
        assert value_in_range(
            actual, result_range
        ), f"GT unsound: gt({a}, {b}) = {actual}, range = {result_range}"

    @given(a=int256_strategy, b=int256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_slt_soundness(self, a: int, b: int) -> None:
        """SLT (signed): result must be in computed range."""
        var_a = IRVariable("%a")
        var_b = IRVariable("%b")
        # Evaluator reads operands[-1] as lhs, operands[-2] as rhs
        inst = make_inst("slt", var_b, var_a)
        state = {var_a: ValueRange.constant(a), var_b: ValueRange.constant(b)}
        result_range = _eval_compare(inst, state)
        actual = eval_evm_slt(to_unsigned(a), to_unsigned(b))
        assert value_in_range(
            actual, result_range
        ), f"SLT unsound: slt({a}, {b}) = {actual}, range = {result_range}"

    @given(a=int256_strategy, b=int256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_sgt_soundness(self, a: int, b: int) -> None:
        """SGT (signed): result must be in computed range."""
        var_a = IRVariable("%a")
        var_b = IRVariable("%b")
        # Evaluator reads operands[-1] as lhs, operands[-2] as rhs
        inst = make_inst("sgt", var_b, var_a)
        state = {var_a: ValueRange.constant(a), var_b: ValueRange.constant(b)}
        result_range = _eval_compare(inst, state)
        actual = eval_evm_sgt(to_unsigned(a), to_unsigned(b))
        assert value_in_range(
            actual, result_range
        ), f"SGT unsound: sgt({a}, {b}) = {actual}, range = {result_range}"

    @given(a=int256_strategy, b=int256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_eq_soundness(self, a: int, b: int) -> None:
        """EQ: result must be in computed range."""
        var_a = IRVariable("%a")
        var_b = IRVariable("%b")
        # EQ is commutative, but keep consistent with other tests
        inst = make_inst("eq", var_b, var_a)
        state = {var_a: ValueRange.constant(a), var_b: ValueRange.constant(b)}
        result_range = _eval_eq(inst, state)
        actual = eval_evm_eq(to_unsigned(a), to_unsigned(b))
        assert value_in_range(
            actual, result_range
        ), f"EQ unsound: eq({a}, {b}) = {actual}, range = {result_range}"

    @given(a=int256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_iszero_soundness(self, a: int) -> None:
        """ISZERO: result must be in computed range."""
        var_a = IRVariable("%a")
        inst = make_inst("iszero", var_a)
        state = {var_a: ValueRange.constant(a)}
        result_range = _eval_iszero(inst, state)
        actual = eval_evm_iszero(to_unsigned(a))
        assert value_in_range(
            actual, result_range
        ), f"ISZERO unsound: iszero({a}) = {actual}, range = {result_range}"

    def test_lt_minus_one_vs_one(self) -> None:
        """Critical: lt(-1, 1) must be 0 (unsigned: MAX_UINT > 1)."""
        var_a = IRVariable("%a")
        var_b = IRVariable("%b")
        # Evaluator reads operands[-1] as lhs, operands[-2] as rhs
        inst = make_inst("lt", var_b, var_a)
        state = {var_a: ValueRange.constant(-1), var_b: ValueRange.constant(1)}
        result_range = _eval_compare(inst, state)
        # -1 as unsigned is MAX_UINT, MAX_UINT > 1, so lt returns 0
        assert value_in_range(0, result_range), f"lt(-1, 1) must include 0, got {result_range}"

    def test_eq_minus_one_and_max_uint(self) -> None:
        """Critical: eq(-1, MAX_UINT) must be 1 (same bit pattern)."""
        var_a = IRVariable("%a")
        var_b = IRVariable("%b")
        # EQ is commutative, but keep consistent
        inst = make_inst("eq", var_b, var_a)
        # Both -1 and UNSIGNED_MAX are the same 256-bit pattern
        state = {var_a: ValueRange.constant(-1), var_b: ValueRange.constant(-1)}
        result_range = _eval_eq(inst, state)
        assert value_in_range(1, result_range), f"eq(-1, -1) must include 1, got {result_range}"


# =============================================================================
# SOUNDNESS TESTS: BITWISE OPERATIONS
# =============================================================================


class TestBitwiseSoundness:
    """Property tests verifying bitwise evaluator soundness."""

    @given(value=small_uint_strategy, mask=byte_strategy)
    @settings(deadline=None, max_examples=200)
    def test_and_soundness(self, value: int, mask: int) -> None:
        """AND with literal mask: result must be in computed range."""
        var_x = IRVariable("%x")
        inst = make_inst("and", var_x, mask)
        state = {var_x: ValueRange.constant(value)}
        result_range = _eval_and(inst, state)
        actual = eval_evm_and(value, mask)
        assert value_in_range(
            actual, result_range
        ), f"AND unsound: {value} & {mask} = {actual}, range = {result_range}"

    @given(shift=shift_strategy, value=small_uint_strategy)
    @settings(deadline=None, max_examples=200)
    def test_shr_soundness(self, shift: int, value: int) -> None:
        """SHR: result must be in computed range."""
        var_x = IRVariable("%x")
        # Syntax: shr SHIFT, VALUE -> operands[-1]=SHIFT, operands[-2]=VALUE
        inst = make_inst("shr", var_x, shift)
        state = {var_x: ValueRange.constant(value)}
        result_range = _eval_shr(inst, state)
        actual = eval_evm_shr(shift, value)
        assert value_in_range(
            actual, result_range
        ), f"SHR unsound: {value} >> {shift} = {actual}, range = {result_range}"

    @given(shift=shift_strategy, value=small_uint_strategy)
    @settings(deadline=None, max_examples=200)
    def test_shl_soundness(self, shift: int, value: int) -> None:
        """SHL: result must be in computed range."""
        var_x = IRVariable("%x")
        inst = make_inst("shl", var_x, shift)
        state = {var_x: ValueRange.constant(value)}
        result_range = _eval_shl(inst, state)
        actual = eval_evm_shl(shift, value)
        assert value_in_range(
            actual, result_range
        ), f"SHL unsound: {value} << {shift} = {actual}, range = {result_range}"

    @given(shift=shift_strategy, value=int256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_sar_soundness(self, shift: int, value: int) -> None:
        """SAR (arithmetic shift): result must be in computed range."""
        var_x = IRVariable("%x")
        inst = make_inst("sar", var_x, shift)
        state = {var_x: ValueRange.constant(value)}
        result_range = _eval_sar(inst, state)
        actual = eval_evm_sar(shift, to_unsigned(value))
        assert value_in_range(
            actual, result_range
        ), f"SAR unsound: sar({shift}, {value}) = {actual}, range = {result_range}"

    @given(n=byte_strategy, value=uint256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_byte_soundness(self, n: int, value: int) -> None:
        """BYTE: result must be in computed range."""
        var_x = IRVariable("%x")
        inst = make_inst("byte", var_x, n)
        state = {var_x: ValueRange.constant(to_signed(value))}
        result_range = _eval_byte(inst, state)
        actual = eval_evm_byte(n, value)
        assert value_in_range(
            actual, result_range
        ), f"BYTE unsound: byte({n}, {value}) = {actual}, range = {result_range}"

    def test_shift_by_256_returns_zero(self) -> None:
        """Shift by 256 must return 0."""
        var_x = IRVariable("%x")
        for opcode, eval_fn in [("shr", _eval_shr), ("shl", _eval_shl)]:
            inst = make_inst(opcode, var_x, 256)
            state = {var_x: ValueRange.constant(UINT256_MAX)}
            result_range = eval_fn(inst, state)
            assert value_in_range(0, result_range), f"{opcode} by 256 must include 0"

    @given(a=uint256_strategy, b=uint256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_or_soundness(self, a: int, b: int) -> None:
        """OR: result must be in computed range."""
        var_a = IRVariable("%a")
        var_b = IRVariable("%b")
        inst = make_inst("or", var_b, var_a)
        state = {var_a: ValueRange.constant(to_signed(a)), var_b: ValueRange.constant(to_signed(b))}
        result_range = _eval_or(inst, state)
        actual = eval_evm_or(a, b)
        assert value_in_range(
            actual, result_range
        ), f"OR unsound: {a} | {b} = {actual}, range = {result_range}"

    @given(a=uint256_strategy, b=uint256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_xor_soundness(self, a: int, b: int) -> None:
        """XOR: result must be in computed range."""
        var_a = IRVariable("%a")
        var_b = IRVariable("%b")
        inst = make_inst("xor", var_b, var_a)
        state = {var_a: ValueRange.constant(to_signed(a)), var_b: ValueRange.constant(to_signed(b))}
        result_range = _eval_xor(inst, state)
        actual = eval_evm_xor(a, b)
        assert value_in_range(
            actual, result_range
        ), f"XOR unsound: {a} ^ {b} = {actual}, range = {result_range}"

    @given(a=uint256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_not_soundness(self, a: int) -> None:
        """NOT: result must be in computed range."""
        var_a = IRVariable("%a")
        inst = make_inst("not", var_a)
        state = {var_a: ValueRange.constant(to_signed(a))}
        result_range = _eval_not(inst, state)
        actual = eval_evm_not(a)
        assert value_in_range(
            actual, result_range
        ), f"NOT unsound: ~{a} = {actual}, range = {result_range}"

    def test_or_with_zero_identity(self) -> None:
        """OR with 0 should return the other operand's range."""
        var_x = IRVariable("%x")
        test_range = ValueRange((10, 20))
        inst = make_inst("or", var_x, 0)
        state = {var_x: test_range}
        result_range = _eval_or(inst, state)
        assert (
            result_range.bounds == test_range.bounds
        ), f"OR with 0 should preserve range, got {result_range}"

    def test_or_with_all_ones_absorbing(self) -> None:
        """OR with -1 (all bits set) should return -1."""
        var_x = IRVariable("%x")
        inst = make_inst("or", var_x, -1)
        state = {var_x: ValueRange.top()}
        result_range = _eval_or(inst, state)
        assert (
            result_range.is_constant and result_range.lo == -1
        ), f"OR with -1 should give -1, got {result_range}"

    def test_xor_self_is_zero(self) -> None:
        """XOR of variable with itself should be 0."""
        var_x = IRVariable("%x")
        inst = make_inst("xor", var_x, var_x)
        state = {var_x: ValueRange.top()}
        result_range = _eval_xor(inst, state)
        assert (
            result_range.is_constant and result_range.lo == 0
        ), f"XOR self should be 0, got {result_range}"

    def test_not_involution(self) -> None:
        """NOT(NOT(x)) should equal x for constants."""
        test_val = 12345
        var_x = IRVariable("%x")

        # First NOT
        inst1 = make_inst("not", var_x)
        state1 = {var_x: ValueRange.constant(test_val)}
        result1 = _eval_not(inst1, state1)

        # Second NOT
        var_y = IRVariable("%y")
        inst2 = make_inst("not", var_y)
        state2 = {var_y: result1}
        result2 = _eval_not(inst2, state2)

        assert (
            result2.is_constant and result2.lo == test_val
        ), f"NOT(NOT({test_val})) should be {test_val}, got {result2}"

    def test_and_with_all_ones_identity(self) -> None:
        """AND with -1 (all bits set) should be identity.

        Regression test: Previously returned [0, UNSIGNED_MAX] which doesn't
        include negative values in signed range comparison.
        """
        var_x = IRVariable("%x")
        # Input range includes negatives
        test_range = ValueRange((-128, 127))
        inst = make_inst("and", var_x, -1)
        state = {var_x: test_range}
        result_range = _eval_and(inst, state)

        # AND with -1 is identity, should preserve input range
        assert (
            result_range.bounds == test_range.bounds
        ), f"AND with -1 should be identity, expected {test_range}, got {result_range}"

        # Verify a negative value is in range
        assert value_in_range(to_unsigned(-128), result_range), "-128 should be in result of AND -1"

    def test_xor_self_with_bottom_returns_bottom(self) -> None:
        """XOR of variable with itself when variable is BOTTOM should return BOTTOM.

        Regression test: Previously returned 0 without checking for BOTTOM input.
        """
        var_x = IRVariable("%x")
        inst = make_inst("xor", var_x, var_x)
        state = {var_x: ValueRange.empty()}
        result_range = _eval_xor(inst, state)

        assert (
            result_range.is_empty
        ), f"XOR self with BOTTOM input should return BOTTOM, got {result_range}"

    def test_and_with_bottom_returns_bottom(self) -> None:
        """AND with BOTTOM input should return BOTTOM."""
        var_x = IRVariable("%x")
        inst = make_inst("and", var_x, 255)
        state = {var_x: ValueRange.empty()}
        result_range = _eval_and(inst, state)

        assert (
            result_range.is_empty
        ), f"AND with BOTTOM input should return BOTTOM, got {result_range}"


# =============================================================================
# SOUNDNESS TESTS: SIGNEXTEND
# =============================================================================


class TestSignextendSoundness:
    """Property tests verifying signextend evaluator soundness."""

    @given(b=st.integers(min_value=0, max_value=30), value=uint256_strategy)
    @settings(deadline=None, max_examples=200)
    def test_signextend_soundness(self, b: int, value: int) -> None:
        """SIGNEXTEND: result must be in computed range."""
        var_x = IRVariable("%x")
        # Evaluator reads operands[-1] as byte index, operands[-2] as value
        inst = make_inst("signextend", var_x, b)
        state = {var_x: ValueRange.constant(to_signed(value))}
        result_range = _eval_signextend(inst, state)
        actual = eval_evm_signextend(b, value)
        actual_signed = to_signed(actual)
        assert value_in_range_signed(actual_signed, result_range), (
            f"SIGNEXTEND unsound: signextend({b}, {value}) = {actual_signed}, "
            f"range = {result_range}"
        )

    @given(b=st.integers(min_value=0, max_value=3))
    @settings(deadline=None, max_examples=50)
    def test_signextend_output_bounds(self, b: int) -> None:
        """SIGNEXTEND output must be in expected signed range."""
        bits = 8 * (b + 1)
        expected_lo = -(1 << (bits - 1))
        expected_hi = (1 << (bits - 1)) - 1

        var_x = IRVariable("%x")
        # Evaluator reads operands[-1] as byte index, operands[-2] as value
        inst = make_inst("signextend", var_x, b)
        state = {var_x: ValueRange.top()}
        result_range = _eval_signextend(inst, state)

        assert (
            result_range.lo == expected_lo
        ), f"signextend({b}) lo: expected {expected_lo}, got {result_range.lo}"
        assert (
            result_range.hi == expected_hi
        ), f"signextend({b}) hi: expected {expected_hi}, got {result_range.hi}"

    def test_signextend_constant_folding(self) -> None:
        """SIGNEXTEND with constant input should give exact result."""
        # signextend(0, 384) where 384 = 0x180
        # Low byte = 0x80, sign bit set, result = -128
        var_x = IRVariable("%x")
        # Evaluator reads operands[-1] as byte index, operands[-2] as value
        inst = make_inst("signextend", var_x, 0)
        state = {var_x: ValueRange.constant(384)}
        result_range = _eval_signextend(inst, state)

        expected = -128
        assert (
            result_range.is_constant and result_range.lo == expected
        ), f"signextend(0, 384) should be {expected}, got {result_range}"

    def test_signextend_31_is_identity(self) -> None:
        """SIGNEXTEND with b >= 31 should be identity."""
        var_x = IRVariable("%x")
        # Evaluator reads operands[-1] as byte index, operands[-2] as value
        inst = make_inst("signextend", var_x, 31)
        test_val = 12345
        state = {var_x: ValueRange.constant(test_val)}
        result_range = _eval_signextend(inst, state)

        assert (
            result_range.is_constant and result_range.lo == test_val
        ), f"signextend(31, {test_val}) should be identity"
