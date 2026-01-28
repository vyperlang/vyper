"""Comprehensive tests for _eval_byte evaluator.

The byte instruction extracts the N-th byte (big-endian) from a 256-bit value.
byte(N, x) returns the N-th byte from the high end (byte 0 is MSB, byte 31 is LSB).
When N >= 32, the result is always 0.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from vyper.venom.analysis.variable_range.evaluators import _eval_byte
from vyper.venom.analysis.variable_range.value_range import ValueRange
from vyper.venom.basicblock import IRInstruction, IRLiteral, IRVariable

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def make_byte_inst(index_op, value_op) -> IRInstruction:
    """Create a byte instruction.

    Note: operand order is operands[-1] = index, operands[-2] = value.
    """
    ops = []
    for op in [value_op, index_op]:  # Reversed order for operand array
        if isinstance(op, int):
            ops.append(IRLiteral(op))
        else:
            ops.append(op)
    return IRInstruction("byte", ops)


def eval_evm_byte(index: int, value: int) -> int:
    """Evaluate EVM BYTE operation for reference.

    byte(N, x) returns the N-th byte from the high end (big-endian).
    """
    if index >= 32:
        return 0
    # Byte N is at bit position (31-N)*8 to (31-N)*8+7
    shift = (31 - index) * 8
    return (value >> shift) & 0xFF


def to_unsigned(val: int) -> int:
    """Convert signed 256-bit value to unsigned."""
    if val < 0:
        return val + (2**256)
    return val


def value_in_range(val: int, rng: ValueRange) -> bool:
    """Check if an unsigned value is contained in a range."""
    if rng.is_top:
        return True
    if rng.is_empty:
        return False
    # For byte results, they are always unsigned [0, 255]
    # Convert to signed for comparison if needed
    if val > 2**255 - 1:
        signed_val = val - 2**256
    else:
        signed_val = val
    return rng.lo <= signed_val <= rng.hi


# =============================================================================
# CASE 1: index >= 32 returns constant(0)
# =============================================================================


class TestByteIndexOutOfRange:
    """Test that byte with index >= 32 returns constant(0)."""

    def test_index_32_returns_zero(self) -> None:
        """byte(32, x) should return 0."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(32, var_x)
        state = {var_x: ValueRange.top()}
        result = _eval_byte(inst, state)
        assert result.is_constant
        assert result.lo == 0

    def test_index_33_returns_zero(self) -> None:
        """byte(33, x) should return 0."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(33, var_x)
        state = {var_x: ValueRange.constant(0xFFFFFFFFFFFFFFFF)}
        result = _eval_byte(inst, state)
        assert result.is_constant
        assert result.lo == 0

    def test_index_255_returns_zero(self) -> None:
        """byte(255, x) should return 0."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(255, var_x)
        state = {var_x: ValueRange.top()}
        result = _eval_byte(inst, state)
        assert result.is_constant
        assert result.lo == 0

    def test_index_max_uint_returns_zero(self) -> None:
        """byte(MAX_UINT, x) should return 0."""
        var_x = IRVariable("%x")
        # Using a large literal value
        inst = make_byte_inst(2**64, var_x)
        state = {var_x: ValueRange.top()}
        result = _eval_byte(inst, state)
        assert result.is_constant
        assert result.lo == 0


# =============================================================================
# CASE 2: value_range is empty returns empty
# =============================================================================


class TestByteEmptyRange:
    """Test that byte with empty value range returns empty."""

    def test_empty_value_range_returns_empty(self) -> None:
        """byte(N, empty) should return empty."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(0, var_x)
        state = {var_x: ValueRange.empty()}
        result = _eval_byte(inst, state)
        assert result.is_empty

    def test_empty_value_range_any_index(self) -> None:
        """byte with empty value range returns empty for any index."""
        var_x = IRVariable("%x")
        for idx in [0, 15, 31, 32]:
            inst = make_byte_inst(idx, var_x)
            state = {var_x: ValueRange.empty()}
            result = _eval_byte(inst, state)
            assert result.is_empty, f"Failed for index {idx}"


# =============================================================================
# CASE 3: value_range is top returns bytes_range [0, 255]
# =============================================================================


class TestByteTopRange:
    """Test that byte with TOP value range returns bytes_range [0, 255]."""

    def test_top_value_range_returns_bytes_range(self) -> None:
        """byte(N, TOP) should return [0, 255]."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(0, var_x)
        state = {var_x: ValueRange.top()}
        result = _eval_byte(inst, state)
        assert result.lo == 0
        assert result.hi == 255

    def test_top_value_range_all_valid_indices(self) -> None:
        """byte with TOP value range returns [0, 255] for indices 0-31."""
        var_x = IRVariable("%x")
        for idx in range(32):
            inst = make_byte_inst(idx, var_x)
            state = {var_x: ValueRange.top()}
            result = _eval_byte(inst, state)
            assert result.lo == 0, f"Failed for index {idx}"
            assert result.hi == 255, f"Failed for index {idx}"


# =============================================================================
# CASE 4: index is not a literal (variable) returns bytes_range [0, 255]
# =============================================================================


class TestByteVariableIndex:
    """Test that byte with variable index returns bytes_range [0, 255]."""

    def test_variable_index_returns_bytes_range(self) -> None:
        """byte(%idx, x) with variable index should return [0, 255]."""
        var_idx = IRVariable("%idx")
        var_x = IRVariable("%x")
        inst = make_byte_inst(var_idx, var_x)
        state = {var_idx: ValueRange((0, 31)), var_x: ValueRange.constant(0x1234)}
        result = _eval_byte(inst, state)
        assert result.lo == 0
        assert result.hi == 255

    def test_variable_index_with_constant_value(self) -> None:
        """byte with variable index returns [0, 255] even with constant value."""
        var_idx = IRVariable("%idx")
        inst = make_byte_inst(var_idx, 0xFF00FF)
        state = {var_idx: ValueRange.constant(0)}
        result = _eval_byte(inst, state)
        # Even though value is constant, index is variable so we can't
        # determine which byte to extract
        assert result.lo == 0
        assert result.hi == 255


# =============================================================================
# CASE 5: value_range.lo < 0 (negative) returns bytes_range [0, 255]
# =============================================================================


class TestByteNegativeRange:
    """Test that byte with negative value range returns bytes_range [0, 255]."""

    def test_negative_constant_returns_bytes_range(self) -> None:
        """byte(N, negative) should return [0, 255] (conservative)."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(31, var_x)  # LSB
        state = {var_x: ValueRange.constant(-1)}
        result = _eval_byte(inst, state)
        # The function returns bytes_range for negative values
        assert result.lo == 0
        assert result.hi == 255

    def test_negative_range_returns_bytes_range(self) -> None:
        """byte with range including negatives returns [0, 255]."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(0, var_x)
        state = {var_x: ValueRange((-128, 127))}
        result = _eval_byte(inst, state)
        assert result.lo == 0
        assert result.hi == 255

    def test_purely_negative_range_returns_bytes_range(self) -> None:
        """byte with purely negative range returns [0, 255]."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(15, var_x)
        state = {var_x: ValueRange((-1000, -1))}
        result = _eval_byte(inst, state)
        assert result.lo == 0
        assert result.hi == 255


# =============================================================================
# CASE 6: value_range.hi < (1 << shift) returns constant(0)
# =============================================================================


class TestByteValueBelowBytePosition:
    """Test that byte returns 0 when value is entirely below byte position."""

    def test_byte_0_small_value(self) -> None:
        """byte(0, small_value) where small_value < 2^248 returns 0."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(0, var_x)
        # Byte 0 extracts bits 248-255, so any value < 2^248 has byte 0 = 0
        state = {var_x: ValueRange((0, 2**247))}
        result = _eval_byte(inst, state)
        assert result.is_constant
        assert result.lo == 0

    def test_byte_30_small_value(self) -> None:
        """byte(30, x) where x < 256 returns 0."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(30, var_x)
        # Byte 30 extracts bits 8-15, so any value < 256 has byte 30 = 0
        state = {var_x: ValueRange((0, 255))}
        result = _eval_byte(inst, state)
        assert result.is_constant
        assert result.lo == 0

    def test_byte_20_value_below_position(self) -> None:
        """byte(20, x) where x < 2^88 returns 0."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(20, var_x)
        # Byte 20 extracts bits at position (31-20)*8 = 88 to 95
        # Any value < 2^88 has byte 20 = 0
        state = {var_x: ValueRange((0, 2**87))}
        result = _eval_byte(inst, state)
        assert result.is_constant
        assert result.lo == 0


# =============================================================================
# CASE 7: Same prefix case - bounded byte range
# =============================================================================


class TestByteSamePrefixBounded:
    """Test bounded byte range when lo and hi share the same prefix."""

    def test_byte_31_small_range(self) -> None:
        """byte(31, [0, 10]) returns [0, 10]."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(31, var_x)
        # Byte 31 is the LSB, extracting bits 0-7
        state = {var_x: ValueRange((0, 10))}
        result = _eval_byte(inst, state)
        assert result.lo == 0
        assert result.hi == 10

    def test_byte_31_range_0_255(self) -> None:
        """byte(31, [0, 255]) returns [0, 255]."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(31, var_x)
        state = {var_x: ValueRange((0, 255))}
        result = _eval_byte(inst, state)
        assert result.lo == 0
        assert result.hi == 255

    def test_byte_31_range_100_200(self) -> None:
        """byte(31, [100, 200]) returns [100, 200]."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(31, var_x)
        state = {var_x: ValueRange((100, 200))}
        result = _eval_byte(inst, state)
        assert result.lo == 100
        assert result.hi == 200

    def test_byte_30_range_with_same_prefix(self) -> None:
        """byte(30, [0x100, 0x1FF]) returns [1, 1] (same high byte)."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(30, var_x)
        # 0x100 to 0x1FF all have byte 30 = 1
        state = {var_x: ValueRange((0x100, 0x1FF))}
        result = _eval_byte(inst, state)
        assert result.lo == 1
        assert result.hi == 1

    def test_byte_30_range_partial(self) -> None:
        """byte(30, [0x180, 0x1C0]) returns [1, 1]."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(30, var_x)
        state = {var_x: ValueRange((0x180, 0x1C0))}
        result = _eval_byte(inst, state)
        assert result.lo == 1
        assert result.hi == 1


# =============================================================================
# CASE 8: Different prefix case - returns bytes_range [0, 255]
# =============================================================================


class TestByteDifferentPrefix:
    """Test that byte returns [0, 255] when range spans byte boundaries."""

    def test_byte_31_spans_boundary(self) -> None:
        """byte(31, [0, 256]) returns [0, 255] (spans byte 31 boundary)."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(31, var_x)
        # Range spans from 0x00 to 0x100, byte 31 covers full range
        state = {var_x: ValueRange((0, 256))}
        result = _eval_byte(inst, state)
        assert result.lo == 0
        assert result.hi == 255

    def test_byte_30_spans_boundary(self) -> None:
        """byte(30, [0, 0x20000]) returns [0, 255] (spans byte 30 boundary)."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(30, var_x)
        # For byte 30: shift = (31-30)*8 = 8
        # lo_prefix = lo >> 16, hi_prefix = hi >> 16
        # [0, 0x20000] has lo_prefix=0, hi_prefix=2 (different)
        state = {var_x: ValueRange((0, 0x20000))}
        result = _eval_byte(inst, state)
        assert result.lo == 0
        assert result.hi == 255

    def test_byte_31_large_range(self) -> None:
        """byte(31, [0, 1000]) returns [0, 255]."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(31, var_x)
        state = {var_x: ValueRange((0, 1000))}
        result = _eval_byte(inst, state)
        assert result.lo == 0
        assert result.hi == 255

    def test_byte_29_spans_boundary(self) -> None:
        """byte(29, [0x10000, 0x3000000]) returns [0, 255]."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(29, var_x)
        # For byte 29: shift = (31-29)*8 = 16
        # lo_prefix = lo >> 24, hi_prefix = hi >> 24
        # [0x10000, 0x3000000] has lo_prefix=0, hi_prefix=3 (different)
        state = {var_x: ValueRange((0x10000, 0x3000000))}
        result = _eval_byte(inst, state)
        assert result.lo == 0
        assert result.hi == 255


# =============================================================================
# CASE 9: Edge cases - byte 0 (MSB), byte 31 (LSB), values at boundaries
# =============================================================================


class TestByteEdgeCases:
    """Test edge cases for byte extraction."""

    def test_byte_0_all_ones(self) -> None:
        """byte(0, -1) should return [0, 255] (negative value)."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(0, var_x)
        state = {var_x: ValueRange.constant(-1)}
        result = _eval_byte(inst, state)
        # -1 is 0xFF...FF, so byte 0 = 0xFF = 255
        # But the function returns bytes_range for negative values
        assert result.lo == 0
        assert result.hi == 255

    def test_byte_at_exact_boundary_256(self) -> None:
        """byte(31, [256, 256]) returns [0, 0]."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(31, var_x)
        # 256 = 0x100, byte 31 = 0x00
        state = {var_x: ValueRange.constant(256)}
        result = _eval_byte(inst, state)
        assert result.is_constant
        assert result.lo == 0

    def test_byte_at_exact_boundary_255(self) -> None:
        """byte(31, [255, 255]) returns [255, 255]."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(31, var_x)
        state = {var_x: ValueRange.constant(255)}
        result = _eval_byte(inst, state)
        assert result.is_constant
        assert result.lo == 255

    def test_byte_index_31_boundary_value(self) -> None:
        """Test byte 31 at the boundary between valid and invalid indices."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(31, var_x)
        state = {var_x: ValueRange((128, 255))}
        result = _eval_byte(inst, state)
        assert result.lo == 128
        assert result.hi == 255


# =============================================================================
# SOUNDNESS TESTS (Property-based)
# =============================================================================


class TestByteSoundness:
    """Property-based tests verifying byte evaluator soundness."""

    @given(
        index=st.integers(min_value=0, max_value=31),
        value=st.integers(min_value=0, max_value=2**64),
    )
    @settings(deadline=None, max_examples=200)
    def test_byte_soundness_constants(self, index: int, value: int) -> None:
        """BYTE with constant inputs: result must be in computed range."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(index, var_x)
        state = {var_x: ValueRange.constant(value)}
        result_range = _eval_byte(inst, state)
        actual = eval_evm_byte(index, value)
        assert value_in_range(
            actual, result_range
        ), f"BYTE unsound: byte({index}, {value}) = {actual}, range = {result_range}"

    @given(
        index=st.integers(min_value=32, max_value=1000),
        value=st.integers(min_value=0, max_value=2**256 - 1),
    )
    @settings(deadline=None, max_examples=50)
    def test_byte_soundness_out_of_range_index(self, index: int, value: int) -> None:
        """BYTE with out-of-range index always returns 0."""
        inst = make_byte_inst(index, value)
        result_range = _eval_byte(inst, {})
        assert result_range.is_constant
        assert result_range.lo == 0

    @given(index=st.integers(min_value=0, max_value=31))
    @settings(deadline=None, max_examples=50)
    def test_byte_soundness_top_range(self, index: int) -> None:
        """BYTE with TOP value range must include all possible byte values."""
        var_x = IRVariable("%x")
        inst = make_byte_inst(index, var_x)
        state = {var_x: ValueRange.top()}
        result_range = _eval_byte(inst, state)
        # Result must cover [0, 255]
        assert result_range.lo <= 0
        assert result_range.hi >= 255

    @given(lo=st.integers(min_value=0, max_value=255), hi=st.integers(min_value=0, max_value=255))
    @settings(deadline=None, max_examples=100)
    def test_byte_31_bounded_range_soundness(self, lo: int, hi: int) -> None:
        """BYTE(31, [lo, hi]) must contain all actual byte values."""
        if lo > hi:
            lo, hi = hi, lo
        var_x = IRVariable("%x")
        inst = make_byte_inst(31, var_x)
        state = {var_x: ValueRange((lo, hi))}
        result_range = _eval_byte(inst, state)

        # Check that all values in [lo, hi] produce results in result_range
        for val in range(lo, min(hi + 1, lo + 10)):  # Check first few
            actual = eval_evm_byte(31, val)
            assert value_in_range(
                actual, result_range
            ), f"BYTE unsound: byte(31, {val}) = {actual}, range = {result_range}"

    @given(
        lo=st.integers(min_value=0, max_value=0xFFFF), hi=st.integers(min_value=0, max_value=0xFFFF)
    )
    @settings(deadline=None, max_examples=100)
    def test_byte_30_bounded_range_soundness(self, lo: int, hi: int) -> None:
        """BYTE(30, [lo, hi]) must contain all actual byte values."""
        if lo > hi:
            lo, hi = hi, lo
        var_x = IRVariable("%x")
        inst = make_byte_inst(30, var_x)
        state = {var_x: ValueRange((lo, hi))}
        result_range = _eval_byte(inst, state)

        # Check bounds
        actual_lo = eval_evm_byte(30, lo)
        actual_hi = eval_evm_byte(30, hi)

        # The result range should contain both bounds (at minimum)
        assert value_in_range(
            actual_lo, result_range
        ), f"BYTE unsound: byte(30, {lo}) = {actual_lo}, range = {result_range}"
        assert value_in_range(
            actual_hi, result_range
        ), f"BYTE unsound: byte(30, {hi}) = {actual_hi}, range = {result_range}"


# =============================================================================
# INTEGRATION TESTS (using full analysis)
# =============================================================================


class TestByteIntegration:
    """Integration tests using the full variable range analysis."""

    def _analyze(self, source: str):
        from vyper.venom.analysis import IRAnalysesCache
        from vyper.venom.analysis.variable_range import VariableRangeAnalysis
        from vyper.venom.parser import parse_venom

        ctx = parse_venom(source)
        fn = next(iter(ctx.functions.values()))
        analyses = IRAnalysesCache(fn)
        analysis = analyses.request_analysis(VariableRangeAnalysis)
        return analysis, fn

    def test_byte_basic_range(self) -> None:
        """Test basic byte extraction through analysis."""
        analysis, fn = self._analyze(
            """
            function test {
            entry:
                %x = calldataload 0
                %b = byte 0, %x
                jmp @exit

            exit:
                stop
            }
            """
        )

        entry = fn.get_basic_block("entry")
        byte_inst = entry.instructions[1]
        assert byte_inst.output is not None
        rng = analysis.get_range(byte_inst.output, entry.instructions[-1])
        assert rng.lo == 0
        assert rng.hi == 255

    def test_byte_out_of_range_index_integration(self) -> None:
        """Test byte with index >= 32 through analysis."""
        analysis, fn = self._analyze(
            """
            function test {
            entry:
                %x = calldataload 0
                %b = byte 32, %x
                jmp @exit

            exit:
                stop
            }
            """
        )

        entry = fn.get_basic_block("entry")
        byte_inst = entry.instructions[1]
        assert byte_inst.output is not None
        rng = analysis.get_range(byte_inst.output, entry.instructions[-1])
        assert rng.lo == 0 and rng.hi == 0

    def test_byte_with_bounded_value(self) -> None:
        """Test byte extraction from bounded value."""
        analysis, fn = self._analyze(
            """
            function test {
            entry:
                %raw = calldataload 0
                %x = mod %raw, 100
                %b = byte 31, %x
                jmp @exit

            exit:
                stop
            }
            """
        )

        entry = fn.get_basic_block("entry")
        byte_inst = next(inst for inst in entry.instructions if inst.opcode == "byte")
        assert byte_inst.output is not None
        rng = analysis.get_range(byte_inst.output, entry.instructions[-1])
        # x is in [0, 99], byte 31 of [0, 99] is [0, 99]
        assert rng.lo == 0
        assert rng.hi == 99

    def test_byte_constant_value(self) -> None:
        """Test byte extraction from constant value."""
        analysis, fn = self._analyze(
            """
            function test {
            entry:
                %x = 0x1234
                %b = byte 30, %x
                jmp @exit

            exit:
                stop
            }
            """
        )

        entry = fn.get_basic_block("entry")
        byte_inst = entry.instructions[1]
        assert byte_inst.output is not None
        rng = analysis.get_range(byte_inst.output, entry.instructions[-1])
        # 0x1234 byte 30 = 0x12
        assert rng.lo == 0x12 and rng.hi == 0x12

    def test_byte_value_below_byte_position(self) -> None:
        """Test byte returns 0 when value is below byte position."""
        analysis, fn = self._analyze(
            """
            function test {
            entry:
                %raw = calldataload 0
                %x = mod %raw, 256
                %b = byte 30, %x
                jmp @exit

            exit:
                stop
            }
            """
        )

        entry = fn.get_basic_block("entry")
        byte_inst = next(inst for inst in entry.instructions if inst.opcode == "byte")
        assert byte_inst.output is not None
        rng = analysis.get_range(byte_inst.output, entry.instructions[-1])
        # x is in [0, 255], byte 30 extracts bits 8-15 which are all 0
        assert rng.lo == 0 and rng.hi == 0

    def test_byte_with_condition_narrowed_range(self) -> None:
        """Test byte with range narrowed by conditional branch.

        Original reviewer example: when %x < 10 in the then branch,
        byte 31 (LSB) should be [0, 9], not [0, 255].
        """
        analysis, fn = self._analyze(
            """
            function test {
            main:
                %x = calldataload 0
                %cond = lt %x, 10
                jnz %cond, @then, @else

            then:
                %b = byte 31, %x
                sink %b

            else:
                sink %x
            }
            """
        )

        then_block = fn.get_basic_block("then")
        byte_inst = next(inst for inst in then_block.instructions if inst.opcode == "byte")
        assert byte_inst.output is not None
        rng = analysis.get_range(byte_inst.output, then_block.instructions[-1])
        # In then branch, %x is in [0, 9], so byte 31 (LSB) is [0, 9]
        assert rng.lo == 0 and rng.hi == 9

    def test_byte_msb_with_condition_narrowed_range(self) -> None:
        """Test MSB byte extraction with range narrowed by conditional branch.

        When %x < 10, byte 0 (MSB) should be 0 since 9 < 2^248.
        """
        analysis, fn = self._analyze(
            """
            function test {
            main:
                %x = calldataload 0
                %cond = lt %x, 10
                jnz %cond, @then, @else

            then:
                %b = byte 0, %x
                sink %b

            else:
                sink %x
            }
            """
        )

        then_block = fn.get_basic_block("then")
        byte_inst = next(inst for inst in then_block.instructions if inst.opcode == "byte")
        assert byte_inst.output is not None
        rng = analysis.get_range(byte_inst.output, then_block.instructions[-1])
        # In then branch, %x is in [0, 9], byte 0 (MSB) is always 0
        assert rng.lo == 0 and rng.hi == 0
