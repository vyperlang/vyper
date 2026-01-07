from __future__ import annotations

from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.analysis.variable_range import VariableRangeAnalysis
from vyper.venom.parser import parse_venom


def _analyze(source: str):
    ctx = parse_venom(source)
    fn = next(iter(ctx.functions.values()))
    analyses = IRAnalysesCache(fn)
    analysis = analyses.request_analysis(VariableRangeAnalysis)
    return analysis, fn


def test_add_propagates_constant_range():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 5
            %y = add %x, 7
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    y_var = entry.instructions[1].output
    assert y_var is not None
    jmp_inst = entry.instructions[-1]

    rng = analysis.get_range(y_var, jmp_inst)
    assert rng.lo == 12
    assert rng.hi == 12


def test_branch_refines_lt_bounds():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %cmp = lt %x, 10
            jnz %cmp, @small, @large

        small:
            %a = add %x, 1
            jmp @end

        large:
            %b = add %x, 2
            jmp @end

        end:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    x_var = entry.instructions[0].output
    assert x_var is not None

    small_bb = fn.get_basic_block("small")
    small_add = next(inst for inst in small_bb.instructions if inst.opcode == "add")
    small_range = analysis.get_range(x_var, small_add)
    assert small_range.hi == 9

    large_bb = fn.get_basic_block("large")
    large_jmp = large_bb.instructions[-1]
    large_range = analysis.get_range(x_var, large_jmp)
    # NOTE: For unsigned `lt` false branch with TOP input, we can't narrow because:
    # - x >= 10 in unsigned includes both [10, SIGNED_MAX] AND negative values
    #   (negative signed values are large unsigned values, all >= 10)
    # - We can't represent this discontinuous range, so we return TOP
    # This is the sound/correct behavior for unsigned comparisons.
    assert large_range.is_top


def test_eq_branch_sets_constant():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %cmp = eq %x, 5
            jnz %cmp, @match, @exit

        match:
            %tmp = add %x, 1
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    x_var = entry.instructions[0].output
    assert x_var is not None

    match_bb = fn.get_basic_block("match")
    use_inst = next(inst for inst in match_bb.instructions if inst.opcode == "add")

    rng = analysis.get_range(x_var, use_inst)
    assert rng.lo == 5
    assert rng.hi == 5


def test_iszero_true_branch_forces_zero():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %flag = iszero %x
            jnz %flag, @zero, @exit

        zero:
            %tmp = add %x, 1
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    x_var = entry.instructions[0].output
    assert x_var is not None

    zero_bb = fn.get_basic_block("zero")
    use_inst = next(inst for inst in zero_bb.instructions if inst.opcode == "add")

    rng = analysis.get_range(x_var, use_inst)
    assert rng.lo == 0
    assert rng.hi == 0


def test_phi_merges_ranges():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %flag = calldataload 0
            %cond = iszero %flag
            jnz %cond, @left, @right

        left:
            %lval = 1
            jmp @merge

        right:
            %rval = 20
            jmp @merge

        merge:
            %merged = phi @left, %lval, @right, %rval
            %sink = add %merged, 0
            stop
        }
        """
    )

    merge_bb = fn.get_basic_block("merge")
    phi_inst = merge_bb.instructions[0]
    merged_var = phi_inst.output
    assert merged_var is not None
    use_inst = next(inst for inst in merge_bb.instructions if inst.opcode == "add")

    rng = analysis.get_range(merged_var, use_inst)
    assert rng.lo == 1
    assert rng.hi == 20


def test_byte_range():
    analysis, fn = _analyze(
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


def test_signextend_range():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %v = signextend 0, %x
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    se_inst = entry.instructions[1]
    rng = analysis.get_range(se_inst.output, entry.instructions[-1])
    assert rng.lo == -128
    assert rng.hi == 127


def test_mod_literal_range():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %y = mod %x, 10
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    mod_inst = entry.instructions[1]
    rng = analysis.get_range(mod_inst.output, entry.instructions[-1])
    assert rng.lo == 0
    assert rng.hi == 9


def test_div_literal_range():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 50
            %y = div %x, 2
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    div_inst = entry.instructions[1]
    rng = analysis.get_range(div_inst.output, entry.instructions[-1])
    assert rng.lo == 25
    assert rng.hi == 25


def test_shifts_update_ranges():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 255
            %shr = shr 4, %x
            %y = 10
            %shl = shl 1, %y
            %neg = -8
            %sar = sar 1, %neg
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    shr_inst = entry.instructions[1]
    shl_inst = entry.instructions[3]
    sar_inst = entry.instructions[5]

    shr_rng = analysis.get_range(shr_inst.output, entry.instructions[-1])
    assert shr_rng.lo == 15
    assert shr_rng.hi == 15

    shl_rng = analysis.get_range(shl_inst.output, entry.instructions[-1])
    assert shl_rng.lo == 20
    assert shl_rng.hi == 20

    sar_rng = analysis.get_range(sar_inst.output, entry.instructions[-1])
    assert sar_rng.lo == -4
    assert sar_rng.hi == -4


def test_add_wraps_constants_modulo():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
            %y = add %x, 1
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    add_inst = entry.instructions[1]
    rng = analysis.get_range(add_inst.output, entry.instructions[-1])
    assert rng.lo == 0
    assert rng.hi == 0


def test_sub_wraps_constants_modulo():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0
            %y = sub %x, 1
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    sub_inst = entry.instructions[1]
    rng = analysis.get_range(sub_inst.output, entry.instructions[-1])

    assert rng.lo == -1
    assert rng.hi == -1


def test_add_signed_constants():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = -10
            %y = add %x, 5
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    add_inst = entry.instructions[1]
    rng = analysis.get_range(add_inst.output, entry.instructions[-1])
    assert rng.lo == -5
    assert rng.hi == -5


def test_iszero_false_branch_does_not_force_positive_when_signed():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %a = calldataload 0
            %x = signextend 1, %a   # x in [-32768, 32767]
            %flag = iszero %x
            jnz %flag, @zero, @nonzero

        nonzero:
            %tmp = add %x, 1
            stop
        zero:
            stop
        }
        """
    )

    nonzero_bb = fn.get_basic_block("nonzero")
    use_inst = nonzero_bb.instructions[0]
    x_var = fn.get_basic_block("entry").instructions[1].output  # signextend output

    rng = analysis.get_range(x_var, use_inst)
    # Must still include negative values — lo must be negative
    assert rng.lo < 0
    # We cannot represent "all values except 0" because ValueRange is contiguous,
    # but importantly the range must not force positivity
    assert rng.lo < 0 <= rng.hi


def test_iszero_false_branch_narrows_range_crossing_zero():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = mod %raw, 11               # x in [0, 10]
            %flag = iszero %x
            jnz %flag, @zero, @nonzero

        nonzero:
            %tmp = add %x, 0                # x != 0 here
            stop
        zero:
            stop
        }
        """
    )

    nonzero_bb = fn.get_basic_block("nonzero")
    use_inst = nonzero_bb.instructions[0]
    x_var = next(
        inst for inst in fn.get_basic_block("entry").instructions if inst.opcode == "mod"
    ).output

    rng = analysis.get_range(x_var, use_inst)
    # Range should be narrowed from [0, 10] to [1, 10] on the nonzero branch
    assert rng.lo == 1
    assert rng.hi == 10


def test_iszero_false_branch_narrows_when_proven_nonnegative():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %len = mod %raw, 1000           # len in [0, 999]
            %flag = iszero %len
            jnz %flag, @empty, @loop

        loop:
            %tmp = add %len, 0              # len != 0 here
            stop
        empty:
            stop
        }
        """
    )

    loop_bb = fn.get_basic_block("loop")
    use_inst = loop_bb.instructions[0]
    len_var = next(
        inst for inst in fn.get_basic_block("entry").instructions if inst.opcode == "mod"
    ).output

    rng = analysis.get_range(len_var, use_inst)
    assert rng.lo >= 1  # zero excluded!


def test_add_large_positive_ranges_go_to_top():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %y = add %x, 1
            stop
        }
        """
    )

    y_var = fn.get_basic_block("entry").instructions[1].output
    rng = analysis.get_range(y_var, fn.get_basic_block("entry").instructions[-1])
    assert rng.is_top


def test_add_near_overflow_does_not_wrap_incorrectly():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = mod %raw, 0x100000000000000000000000000000000000000000000000000
            %y = add %x, %x  # should bail to TOP
            stop
        }
        """
    )

    y_inst = next(inst for inst in fn.get_basic_block("entry").instructions if inst.opcode == "add")
    y_var = y_inst.output
    rng = analysis.get_range(y_var, fn.get_basic_block("entry").instructions[-1])
    # Because each operand has width > 2**128 goes to TOP (correct & safe)
    assert rng.is_top


def test_sub_can_go_negative_but_stays_sound():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 5
            %y = sub 0, %x                    # y = -5 exactly (signed)
            stop
        }
        """
    )

    y_inst = next(inst for inst in fn.get_basic_block("entry").instructions if inst.opcode == "sub")
    y_var = y_inst.output
    rng = analysis.get_range(y_var, fn.get_basic_block("entry").instructions[-1])

    assert rng.lo == -5
    assert rng.hi == -5


def test_and_mask_clears_high_bits_correctly():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %addr = calldataload 0
            %lower = and %addr, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
            stop
        }
        """
    )

    lower_var = fn.get_basic_block("entry").instructions[1].output
    rng = analysis.get_range(lower_var, fn.get_basic_block("entry").instructions[-1])
    assert rng.lo == 0
    assert rng.hi == (1 << 160) - 1


def test_sar_on_negative_value_propagates_sign():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = -1                           # all bits 1
            %y = sar 8, %x                    # still -1
            stop
        }
        """
    )

    sar_inst = next(
        inst for inst in fn.get_basic_block("entry").instructions if inst.opcode == "sar"
    )
    rng = analysis.get_range(sar_inst.output, fn.get_basic_block("entry").instructions[-1])
    assert rng.lo == rng.hi == -1


def test_sar_large_shift_handles_mixed_sign_correctly():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %a = calldataload 0
            %x = signextend 3, %a
            %y = sar 40, %x
            stop
        }
        """
    )

    sar_inst = next(
        inst for inst in fn.get_basic_block("entry").instructions if inst.opcode == "sar"
    )
    rng = analysis.get_range(sar_inst.output, fn.get_basic_block("entry").instructions[-1])
    assert rng.lo == -1 and rng.hi == 0


def test_phi_from_signed_and_unsigned_paths():
    """Phi where one arm is known non-negative, other can be negative"""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %cond = calldataload 0
            jnz %cond, @signed, @unsigned

        signed:
            %a = -42
            jmp @merge

        unsigned:
            %b = 100
            jmp @merge

        merge:
            %v = phi @signed, %a, @unsigned, %b
            %sink = add %v, 0
            stop
        }
        """
    )

    v_var = fn.get_basic_block("merge").instructions[0].output
    rng = analysis.get_range(v_var, fn.get_basic_block("merge").instructions[1])
    assert rng.lo == -42
    assert rng.hi == 100


def test_eq_false_branch_does_not_narrow_to_nothing():
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %cmp = eq %x, 999
            jnz %cmp, @match, @continue

        continue:
            %tmp = add %x, 1
            stop
        match:
            stop
        }
        """
    )

    cont_bb = fn.get_basic_block("continue")
    use_inst = cont_bb.instructions[0]
    match_inst = fn.get_basic_block("match").instructions[0]
    x_var = fn.get_basic_block("entry").instructions[0].output

    rng = analysis.get_range(x_var, match_inst)
    assert rng.hi == 999
    assert rng.lo == 999
    assert analysis.get_range(x_var, use_inst).is_top


def test_mul_constants():
    """Test multiplication of two constants."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 7
            %y = mul %x, 6
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    mul_inst = entry.instructions[1]
    rng = analysis.get_range(mul_inst.output, entry.instructions[-1])
    assert rng.lo == 42
    assert rng.hi == 42


def test_mul_constant_by_range():
    """Test multiplication of a constant by a bounded range."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = mod %raw, 10
            %y = mul %x, 5
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    mul_inst = next(inst for inst in entry.instructions if inst.opcode == "mul")
    rng = analysis.get_range(mul_inst.output, entry.instructions[-1])
    assert rng.lo == 0
    assert rng.hi == 45


def test_mul_two_ranges():
    """Test multiplication of two bounded ranges."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw1 = calldataload 0
            %raw2 = calldataload 32
            %x = mod %raw1, 5
            %y = mod %raw2, 4
            %z = mul %x, %y
            jmp @exit

        exit:
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    mul_inst = next(inst for inst in entry.instructions if inst.opcode == "mul")
    rng = analysis.get_range(mul_inst.output, entry.instructions[-1])
    # x in [0, 4], y in [0, 3] => z in [0, 12]
    assert rng.lo == 0
    assert rng.hi == 12


def test_mul_overflow_goes_to_top():
    """Test that multiplication with potential overflow returns TOP."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %y = mul %x, 2
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    mul_inst = next(inst for inst in entry.instructions if inst.opcode == "mul")
    rng = analysis.get_range(mul_inst.output, entry.instructions[-1])
    # x is unbounded, so multiplication can overflow
    assert rng.is_top


def test_mul_large_range_overflow():
    """Test that multiplication of large ranges goes to TOP due to width limit."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = mod %raw, 0x200000000000000000000000000000000
            %y = mul %x, 2
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    mul_inst = next(inst for inst in entry.instructions if inst.opcode == "mul")
    rng = analysis.get_range(mul_inst.output, entry.instructions[-1])
    # Range width > 2^128, should go to TOP
    assert rng.is_top


def test_mul_by_zero():
    """Test multiplication by zero constant."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %y = mul %x, 0
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    mul_inst = next(inst for inst in entry.instructions if inst.opcode == "mul")
    rng = analysis.get_range(mul_inst.output, entry.instructions[-1])
    assert rng.lo == 0
    assert rng.hi == 0


def test_mul_by_one():
    """Test multiplication by one preserves range."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = mod %raw, 100
            %y = mul %x, 1
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    mul_inst = next(inst for inst in entry.instructions if inst.opcode == "mul")
    rng = analysis.get_range(mul_inst.output, entry.instructions[-1])
    assert rng.lo == 0
    assert rng.hi == 99


def test_mul_signed_goes_to_top():
    """Test that multiplication with signed ranges goes to TOP."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = signextend 0, %raw
            %y = mul %x, 2
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    mul_inst = next(inst for inst in entry.instructions if inst.opcode == "mul")
    rng = analysis.get_range(mul_inst.output, entry.instructions[-1])
    # Signed range includes negatives, so goes to TOP
    assert rng.is_top


def test_mul_wraps_on_overflow_constants():
    """Test that constant multiplication wraps correctly on overflow."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = -1
            %y = mul %x, 2
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    mul_inst = next(inst for inst in entry.instructions if inst.opcode == "mul")
    rng = analysis.get_range(mul_inst.output, entry.instructions[-1])
    # -1 * 2 = -2
    assert rng.lo == -2
    assert rng.hi == -2


# =============================================================================
# BUG REGRESSION TESTS
# These tests document known bugs that need to be fixed.
# =============================================================================


def test_bug_lt_negative_constant_gives_wrong_result():
    """
    Bug: lt comparison with negative constant gives wrong result.

    In EVM, -1 is 0xFF..FF (MAX_UINT), so `lt -1, 1` should be 0 (false)
    because MAX_UINT > 1 in unsigned comparison.
    But the analysis returns 1 because it compares -1 < 1 using signed arithmetic.
    """
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = -1
            %cmp = lt %x, 1
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    cmp_inst = entry.instructions[1]
    rng = analysis.get_range(cmp_inst.output, entry.instructions[-1])
    # Bug: Currently returns {1}, should return {0}
    # In EVM unsigned comparison: 0xFF..FF > 1, so lt returns 0
    assert rng.lo == 0 and rng.hi == 0, f"Expected {{0}}, got {rng}"


def test_bug_eq_negative_constant_with_max_uint_miscompile():
    """
    Miscompile: eq with -1 vs MAX_UINT is true in EVM, but analysis treats
    them as distinct and can eliminate a failing assert.
    """
    from vyper.venom.passes.assert_elimination import AssertEliminationPass

    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = -1
            %cmp = eq %x, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
            %ok = iszero %cmp
            assert %ok
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    ok_inst = next(inst for inst in entry.instructions if inst.opcode == "iszero")
    assert_inst = next(inst for inst in entry.instructions if inst.opcode == "assert")
    ok_var = ok_inst.output

    ok_range = analysis.get_range(ok_var, assert_inst)

    # Runtime: eq(-1, MAX_UINT) = 1, ok = iszero 1 = 0, assert FAILS.
    excludes = AssertEliminationPass._range_excludes_zero(ok_range)
    assert not excludes, (
        f"Miscompile: Assert incorrectly eliminated! "
        f"ok_range={ok_range}, but runtime can produce 0"
    )


def test_bug_unsigned_lt_false_branch_excludes_negatives():
    """
    Bug: When unsigned `lt %x, bound` is false and x has a signed range,
    the false branch incorrectly excludes negative values.

    If x is in [-128, 127] (from signextend 0), and `lt %x, 100` is false,
    then x could be:
    - [100, 127] in signed (same in unsigned)
    - [-128, -1] in signed (0xFF80..0xFFFF in unsigned, all > 100)

    The analysis should track both possibilities, but it only tracks [100, 127].
    """
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = signextend 0, %raw
            %cmp = lt %x, 100
            jnz %cmp, @small, @large

        small:
            stop

        large:
            %tmp = add %x, 0
            stop
        }
        """
    )

    large_bb = fn.get_basic_block("large")
    x_var = fn.get_basic_block("entry").instructions[1].output
    x_range = analysis.get_range(x_var, large_bb.instructions[0])

    # Bug: Currently returns [100, 127], missing negative values
    # The range should include negative values (or be TOP/widened)
    # because -128..-1 are large unsigned values that also satisfy "not lt 100"
    assert (
        x_range.lo < 0 or x_range.is_top
    ), f"Expected range to include negatives or be TOP, got {x_range}"


def test_bug_signextend_produces_bottom_for_out_of_range_input():
    """
    Bug: signextend produces bottom when input value is outside the target range.

    signextend operates on the LOW BITS of the input, not the full value.
    For signextend 0, %x where x=384 (0x180):
    - Low byte is 0x80
    - Sign-extended result is -128 (0xFF..80)

    But the analysis intersects the input range [384, 384] with [-128, 127]
    which gives bottom (empty intersection).
    """
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 384
            %y = signextend 0, %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    se_inst = entry.instructions[1]
    rng = analysis.get_range(se_inst.output, entry.instructions[-1])

    # Bug: Currently returns bottom, should return {-128}
    # The signextend of 0x180 takes low byte 0x80 and sign-extends to -128
    assert not rng.is_empty, "Expected non-empty range, got bottom"
    assert rng.lo == -128 and rng.hi == -128, f"Expected {{-128}}, got {rng}"


def test_bug_and_with_signed_range_gives_narrow_hi():
    """
    Bug: AND with a signed range gives an overly narrow upper bound.

    For `and %x, 255` where x is in [-128, 127]:
    - x in [0, 127]: result in [0, 127]
    - x in [-128, -1]: unsigned [0xFF80, 0xFFFF], AND with 0xFF gives [0x80, 0xFF] = [128, 255]

    So the result should be [0, 255], but analysis gives [0, 127].
    """
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = signextend 0, %raw
            %y = and %x, 255
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    and_inst = entry.instructions[2]
    rng = analysis.get_range(and_inst.output, entry.instructions[-1])

    # Bug: Currently returns [0, 127], should return [0, 255]
    # The AND of negative values like -128 (0xFF80) with 0xFF gives 0x80 = 128
    assert rng.hi == 255, f"Expected hi=255, got {rng}"


def test_bug_lt_false_branch_causes_assert_elimination_miscompile():
    """
    Miscompile: The lt false branch narrowing bug can cause
    an assert that CAN FAIL at runtime to be incorrectly eliminated.

    When `lt %x, bound` is false and x has a signed range including negatives,
    the analysis incorrectly excludes negative values. This leads to wrong
    constant folding of subsequent comparisons, which then causes
    _range_excludes_zero to return True, eliminating an assert that can fail.
    """
    from vyper.venom.passes.assert_elimination import AssertEliminationPass

    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = signextend 0, %raw
            %cmp = lt %x, 100
            jnz %cmp, @under, @over

        over:
            %check = lt %x, 128
            assert %check
            stop

        under:
            stop
        }
        """
    )

    over_bb = fn.get_basic_block("over")
    check_inst = over_bb.instructions[0]
    assert_inst = over_bb.instructions[1]
    check_var = check_inst.output

    check_range = analysis.get_range(check_var, assert_inst)

    # Runtime: if x = -1 (0xFF..FF), lt -1, 100 = 0 (takes @over),
    # then check = lt -1, 128 = 0, assert 0 FAILS!
    # Bug: Analysis gives check = {1}, so assert is eliminated
    excludes = AssertEliminationPass._range_excludes_zero(check_range)
    assert not excludes, (
        f"Miscompile: Assert incorrectly eliminated! "
        f"check_range={check_range}, but runtime can produce 0"
    )


def test_bug_gt_true_branch_causes_assert_elimination_miscompile():
    """
    Miscompile: The gt true branch has the same bug as lt false branch.

    When `gt %x, bound` is true and x has a signed range including negatives,
    the analysis incorrectly excludes negative values from the true branch.
    """
    from vyper.venom.passes.assert_elimination import AssertEliminationPass

    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = signextend 0, %raw
            %cmp = gt %x, 50
            jnz %cmp, @high, @low

        high:
            %check = gt %x, 200
            %ok = iszero %check
            assert %ok
            stop

        low:
            stop
        }
        """
    )

    high_bb = fn.get_basic_block("high")
    ok_inst = high_bb.instructions[1]
    assert_inst = high_bb.instructions[2]
    ok_var = ok_inst.output

    ok_range = analysis.get_range(ok_var, assert_inst)

    # Runtime: if x = -1, gt -1, 50 = 1 (takes @high),
    # check = gt -1, 200 = 1, ok = iszero 1 = 0, assert 0 FAILS!
    excludes = AssertEliminationPass._range_excludes_zero(ok_range)
    assert not excludes, (
        f"Miscompile: Assert incorrectly eliminated! "
        f"ok_range={ok_range}, but runtime can produce 0"
    )


def test_bug_iszero_false_branch_causes_assert_elimination_miscompile():
    """
    Miscompile: iszero false branch excludes negative values,
    leading to incorrect assert elimination.

    When iszero is false (value is non-zero), the analysis intersects with
    [1, UNSIGNED_MAX], which excludes negative values from the signed range.
    """
    from vyper.venom.passes.assert_elimination import AssertEliminationPass

    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = signextend 0, %raw
            %flag = iszero %x
            jnz %flag, @zero, @nonzero

        nonzero:
            %y = add %x, 128
            assert %y
            stop

        zero:
            stop
        }
        """
    )

    nonzero_bb = fn.get_basic_block("nonzero")
    add_inst = nonzero_bb.instructions[0]
    assert_inst = nonzero_bb.instructions[1]
    y_var = add_inst.output

    y_range = analysis.get_range(y_var, assert_inst)

    # Runtime: if x = -128, iszero -128 = 0 (takes @nonzero),
    # y = add -128, 128 = 0, assert 0 FAILS!
    excludes = AssertEliminationPass._range_excludes_zero(y_range)
    assert not excludes, (
        f"Miscompile: Assert incorrectly eliminated! "
        f"y_range={y_range}, but runtime can produce 0"
    )


def test_bug_phi_merge_with_bottom_causes_assert_elimination_miscompile():
    """
    Miscompile: signextend bottom bug propagates through phi,
    causing the phi result to be missing one branch's values.

    When signextend produces bottom (due to input outside result range),
    and that bottom is merged in a phi with a valid range, the bottom
    is treated as identity for union, losing that branch's contribution.
    """
    from vyper.venom.passes.assert_elimination import AssertEliminationPass

    analysis, fn = _analyze(
        """
        function test {
        entry:
            %cond = calldataload 0
            jnz %cond, @path1, @path2

        path1:
            %x1 = 384
            %y1 = signextend 0, %x1
            jmp @merge

        path2:
            %x2 = 1
            %y2 = signextend 0, %x2
            jmp @merge

        merge:
            %y = phi @path1, %y1, @path2, %y2
            %check = eq %y, 1
            assert %check
            stop
        }
        """
    )

    merge_bb = fn.get_basic_block("merge")
    check_inst = merge_bb.instructions[1]
    assert_inst = merge_bb.instructions[2]
    check_var = check_inst.output

    check_range = analysis.get_range(check_var, assert_inst)

    # Runtime via path1: y1 = signextend 0, 384 = -128,
    # y = -128, check = eq -128, 1 = 0, assert 0 FAILS!
    excludes = AssertEliminationPass._range_excludes_zero(check_range)
    assert not excludes, (
        f"Miscompile: Assert incorrectly eliminated! "
        f"check_range={check_range}, but runtime can produce 0"
    )
