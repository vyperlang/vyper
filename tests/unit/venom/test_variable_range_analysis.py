from __future__ import annotations

from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.analysis.variable_range import VariableRangeAnalysis
from vyper.venom.analysis.variable_range.value_range import SIGNED_MAX, SIGNED_MIN
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


def test_lt_boundary_zero_true_branch_is_bottom():
    """lt %x, 0 true means x < 0 unsigned, which is impossible → BOTTOM."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %x_mod = mod %x, 100      ; x in [0, 99], ensures non-negative
            %cmp = lt %x_mod, 0
            jnz %cmp, @impossible, @exit

        impossible:
            %sink = add %x_mod, 1
            stop

        exit:
            stop
        }
        """
    )

    impossible_bb = fn.get_basic_block("impossible")
    sink_inst = impossible_bb.instructions[0]
    x_var = next(
        inst for inst in fn.get_basic_block("entry").instructions if inst.opcode == "mod"
    ).output

    rng = analysis.get_range(x_var, sink_inst)
    # True branch of `lt %x, 0` is unreachable since nothing is < 0 unsigned
    assert rng.is_empty


def test_slt_boundary_signed_min_true_branch_is_bottom():
    """slt %x, SIGNED_MIN true means x < SIGNED_MIN signed, impossible → BOTTOM."""
    from vyper.venom.analysis.variable_range.value_range import SIGNED_MIN

    analysis, fn = _analyze(
        f"""
        function test {{
        entry:
            %x = calldataload 0
            %cmp = slt %x, {SIGNED_MIN}
            jnz %cmp, @impossible, @exit

        impossible:
            %sink = add %x, 1
            stop

        exit:
            stop
        }}
        """
    )

    impossible_bb = fn.get_basic_block("impossible")
    sink_inst = impossible_bb.instructions[0]
    x_var = fn.get_basic_block("entry").instructions[0].output

    rng = analysis.get_range(x_var, sink_inst)
    # True branch of `slt %x, SIGNED_MIN` is unreachable
    assert rng.is_empty


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


def test_byte_out_of_range_index():
    """byte(N, x) returns 0 when N >= 32."""
    analysis, fn = _analyze(
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


def test_iszero_false_branch_with_zero_constant_is_bottom():
    """iszero false branch with 0 input should produce BOTTOM (unreachable)."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0
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
    x_var = fn.get_basic_block("entry").instructions[0].output

    rng = analysis.get_range(x_var, use_inst)
    # False branch of iszero 0 is unreachable, so range should be BOTTOM
    assert rng.is_empty


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
# BITWISE OPERATION TESTS (or, xor, not)
# =============================================================================


def test_or_constants():
    """Test OR of two constants."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0xF0
            %y = or %x, 0x0F
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    or_inst = entry.instructions[1]
    rng = analysis.get_range(or_inst.output, entry.instructions[-1])
    # 0xF0 | 0x0F = 0xFF = 255
    assert rng.lo == 255
    assert rng.hi == 255


def test_or_with_zero():
    """Test OR with zero returns the other operand's range."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = mod %raw, 256
            %y = or %x, 0
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    or_inst = next(inst for inst in entry.instructions if inst.opcode == "or")
    rng = analysis.get_range(or_inst.output, entry.instructions[-1])
    # x in [0, 255], OR with 0 should preserve the range
    assert rng.lo == 0
    assert rng.hi == 255


def test_or_with_all_ones():
    """Test OR with -1 (all bits set) returns -1."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %y = or %x, -1
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    or_inst = next(inst for inst in entry.instructions if inst.opcode == "or")
    rng = analysis.get_range(or_inst.output, entry.instructions[-1])
    # OR with -1 (all bits set) always gives -1
    assert rng.lo == -1
    assert rng.hi == -1


def test_xor_constants():
    """Test XOR of two constants."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0xFF
            %y = xor %x, 0x0F
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    xor_inst = entry.instructions[1]
    rng = analysis.get_range(xor_inst.output, entry.instructions[-1])
    # 0xFF ^ 0x0F = 0xF0 = 240
    assert rng.lo == 240
    assert rng.hi == 240


def test_xor_self_is_zero():
    """Test XOR of a variable with itself is 0."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %y = xor %x, %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    xor_inst = next(inst for inst in entry.instructions if inst.opcode == "xor")
    rng = analysis.get_range(xor_inst.output, entry.instructions[-1])
    # x ^ x = 0 always
    assert rng.lo == 0
    assert rng.hi == 0


def test_xor_with_all_ones():
    """Test XOR with -1 flips all bits (same as NOT)."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0
            %y = xor %x, -1
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    xor_inst = next(inst for inst in entry.instructions if inst.opcode == "xor")
    rng = analysis.get_range(xor_inst.output, entry.instructions[-1])
    # 0 ^ -1 = -1 (all bits set)
    assert rng.lo == -1
    assert rng.hi == -1


def test_not_constant():
    """Test NOT of a constant."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0
            %y = not %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    not_inst = entry.instructions[1]
    rng = analysis.get_range(not_inst.output, entry.instructions[-1])
    # ~0 = -1 (all bits set)
    assert rng.lo == -1
    assert rng.hi == -1


def test_not_all_ones():
    """Test NOT of -1 (all bits set) gives 0."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = -1
            %y = not %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    not_inst = entry.instructions[1]
    rng = analysis.get_range(not_inst.output, entry.instructions[-1])
    # ~(-1) = 0
    assert rng.lo == 0
    assert rng.hi == 0


def test_not_specific_value():
    """Test NOT of a specific non-zero value."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 255
            %y = not %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    not_inst = entry.instructions[1]
    rng = analysis.get_range(not_inst.output, entry.instructions[-1])
    # ~255 = UNSIGNED_MAX - 255 = ...FFFFFF00 which is -256 in signed
    assert rng.lo == -256
    assert rng.hi == -256


def test_not_unknown_is_top():
    """Test NOT of unknown value gives TOP."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %y = not %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    not_inst = next(inst for inst in entry.instructions if inst.opcode == "not")
    rng = analysis.get_range(not_inst.output, entry.instructions[-1])
    assert rng.is_top


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


# =============================================================================
# BOUNDARY VALUE TESTS
# These tests verify correct behavior at extreme boundaries.
# =============================================================================


def test_add_at_signed_min_boundary():
    """Test add with SIGNED_MIN constant (using negative literal)."""
    from vyper.venom.analysis.variable_range.value_range import SIGNED_MIN

    analysis, fn = _analyze(
        f"""
        function test {{
        entry:
            %min = {SIGNED_MIN}
            %y = add %min, 1
            stop
        }}
        """
    )

    entry = fn.get_basic_block("entry")
    add_inst = entry.instructions[1]
    rng = analysis.get_range(add_inst.output, entry.instructions[-1])
    # SIGNED_MIN + 1 = SIGNED_MIN + 1 (just above min)
    expected = SIGNED_MIN + 1
    assert rng.lo == expected and rng.hi == expected


def test_sub_at_signed_min_boundary():
    """Test sub that would underflow past SIGNED_MIN."""

    analysis, fn = _analyze(
        f"""
        function test {{
        entry:
            %min = {SIGNED_MIN}
            %y = sub %min, 1
            stop
        }}
        """
    )

    entry = fn.get_basic_block("entry")
    sub_inst = entry.instructions[1]
    rng = analysis.get_range(sub_inst.output, entry.instructions[-1])
    # SIGNED_MIN - 1 wraps to SIGNED_MAX
    expected = SIGNED_MAX
    assert rng.lo == expected and rng.hi == expected


def test_add_at_unsigned_max_boundary():
    """Test add at UNSIGNED_MAX that wraps to 0."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
            %y = add %x, 1
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    add_inst = entry.instructions[1]
    rng = analysis.get_range(add_inst.output, entry.instructions[-1])
    assert rng.lo == 0 and rng.hi == 0


def test_shr_by_255():
    """Test SHR by 255 bits on a large positive value."""
    from vyper.venom.analysis.variable_range.value_range import SIGNED_MAX

    analysis, fn = _analyze(
        f"""
        function test {{
        entry:
            %x = {SIGNED_MAX}
            %y = shr 255, %x
            stop
        }}
        """
    )

    entry = fn.get_basic_block("entry")
    shr_inst = entry.instructions[1]
    rng = analysis.get_range(shr_inst.output, entry.instructions[-1])
    # SIGNED_MAX >> 255 = 0 (because bit 255 is 0 in SIGNED_MAX)
    assert rng.lo == 0 and rng.hi == 0


def test_shr_by_256():
    """Test SHR by 256 bits - should always give 0."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
            %y = shr 256, %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    shr_inst = entry.instructions[1]
    rng = analysis.get_range(shr_inst.output, entry.instructions[-1])
    assert rng.lo == 0 and rng.hi == 0


def test_shl_by_255():
    """Test SHL by 255 bits."""
    from vyper.venom.analysis.variable_range.value_range import SIGNED_MIN

    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 1
            %y = shl 255, %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    shl_inst = entry.instructions[1]
    rng = analysis.get_range(shl_inst.output, entry.instructions[-1])
    # 1 << 255 = 2^255
    # In signed representation: SIGNED_MIN (-2^255)
    # In unsigned representation: 2^255
    # The result should be constant and equal to 2^255 (either representation)
    assert rng.is_constant
    # Accept either signed or unsigned representation
    expected_unsigned = 2**255
    expected_signed = SIGNED_MIN
    assert rng.lo == expected_signed or rng.lo == expected_unsigned


def test_shl_by_256():
    """Test SHL by 256 bits - should always give 0."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
            %y = shl 256, %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    shl_inst = entry.instructions[1]
    rng = analysis.get_range(shl_inst.output, entry.instructions[-1])
    assert rng.lo == 0 and rng.hi == 0


def test_sar_by_255():
    """Test SAR by 255 bits on negative value."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = -1
            %y = sar 255, %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    sar_inst = entry.instructions[1]
    rng = analysis.get_range(sar_inst.output, entry.instructions[-1])
    # -1 >> 255 = -1 (sign extension preserves -1)
    assert rng.lo == -1 and rng.hi == -1


def test_sar_by_256():
    """Test SAR by 256 bits - returns 0 or -1 based on sign."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = -100
            %y = sar 256, %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    sar_inst = entry.instructions[1]
    rng = analysis.get_range(sar_inst.output, entry.instructions[-1])
    # Negative value >> 256 = -1 (all sign bits)
    assert rng.lo == -1 and rng.hi == -1


def test_div_by_zero_returns_zero():
    """Test that DIV by zero returns 0 (EVM spec)."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 12345
            %y = div %x, 0
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    div_inst = entry.instructions[1]
    rng = analysis.get_range(div_inst.output, entry.instructions[-1])
    assert rng.lo == 0 and rng.hi == 0


def test_mod_by_zero_returns_zero():
    """Test that MOD by zero returns 0 (EVM spec)."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 12345
            %y = mod %x, 0
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    mod_inst = entry.instructions[1]
    rng = analysis.get_range(mod_inst.output, entry.instructions[-1])
    assert rng.lo == 0 and rng.hi == 0


def test_byte_index_32():
    """Test byte with index exactly 32 (should return 0)."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
            %b = byte 32, %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    byte_inst = entry.instructions[1]
    rng = analysis.get_range(byte_inst.output, entry.instructions[-1])
    assert rng.lo == 0 and rng.hi == 0


def test_byte_index_255():
    """Test byte with large index (should return 0)."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
            %b = byte 255, %x
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    byte_inst = entry.instructions[1]
    rng = analysis.get_range(byte_inst.output, entry.instructions[-1])
    assert rng.lo == 0 and rng.hi == 0


def test_nested_conditional_refinement_3_levels():
    """Test refinement through 3 levels of nested conditionals."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %x = calldataload 0
            %c1 = lt %x, 1000
            jnz %c1, @level1, @exit

        level1:
            %c2 = lt %x, 100
            jnz %c2, @level2, @exit

        level2:
            %c3 = lt %x, 10
            jnz %c3, @innermost, @exit

        innermost:
            %tmp = add %x, 0
            stop

        exit:
            stop
        }
        """
    )

    innermost_bb = fn.get_basic_block("innermost")
    x_var = fn.get_basic_block("entry").instructions[0].output
    rng = analysis.get_range(x_var, innermost_bb.instructions[0])
    # After 3 levels: x < 1000, x < 100, x < 10 => x in [0, 9]
    assert rng.hi == 9


def test_phi_merge_4_branches():
    """Test phi merging values from 4 different branches."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %sel = calldataload 0
            %c1 = lt %sel, 25
            jnz %c1, @b1, @check2

        check2:
            %c2 = lt %sel, 50
            jnz %c2, @b2, @check3

        check3:
            %c3 = lt %sel, 75
            jnz %c3, @b3, @b4

        b1:
            %v1 = 10
            jmp @merge
        b2:
            %v2 = 20
            jmp @merge
        b3:
            %v3 = 30
            jmp @merge
        b4:
            %v4 = 40
            jmp @merge

        merge:
            %v = phi @b1, %v1, @b2, %v2, @b3, %v3, @b4, %v4
            %sink = add %v, 0
            stop
        }
        """
    )

    merge_bb = fn.get_basic_block("merge")
    v_var = merge_bb.instructions[0].output
    rng = analysis.get_range(v_var, merge_bb.instructions[1])
    # Phi merges [10, 10], [20, 20], [30, 30], [40, 40] => [10, 40]
    assert rng.lo == 10 and rng.hi == 40


def test_signextend_then_unsigned_comparison():
    """Test combination of signextend followed by unsigned comparison."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = signextend 0, %raw
            %cmp = lt %x, 200
            jnz %cmp, @under, @over

        under:
            %tmp = add %x, 0
            stop

        over:
            stop
        }
        """
    )

    under_bb = fn.get_basic_block("under")
    x_var = fn.get_basic_block("entry").instructions[1].output
    under_range = analysis.get_range(x_var, under_bb.instructions[0])
    # x in [-128, 127] initially
    # Unsigned lt 200: values [0, 127] satisfy lt 200
    # But negative values [-128, -1] are large unsigned (>= 2^255) so don't satisfy lt 200
    # So under branch should have x in [0, 127] (or could be narrower)
    # Actually the analysis may return TOP or a wider range due to sign boundary issues
    # The key thing is soundness - if we get a narrow range, it should be correct
    assert under_range.hi <= 199 or under_range.is_top


def test_loop_counter_bounds():
    """Test that loop counter ranges are properly tracked through back edges."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %i = 0
            jmp @loop

        loop:
            %counter = phi @entry, %i, @body, %next
            %done = lt %counter, 10
            jnz %done, @body, @exit

        body:
            %next = add %counter, 1
            jmp @loop

        exit:
            %sink = add %counter, 0
            stop
        }
        """
    )

    # In the body, counter should be in [0, 9] (since lt 10 was true)
    body_bb = fn.get_basic_block("body")
    counter_var = fn.get_basic_block("loop").instructions[0].output
    body_range = analysis.get_range(counter_var, body_bb.instructions[0])
    # Counter in body: must satisfy lt 10, so in [0, 9]
    assert body_range.hi <= 9 or body_range.is_top

    # At exit, counter should be >= 10 (since lt 10 was false)
    exit_bb = fn.get_basic_block("exit")
    exit_range = analysis.get_range(counter_var, exit_bb.instructions[0])
    # Counter at exit: must NOT satisfy lt 10
    # This might be TOP or a range >= 10
    assert exit_range.lo >= 10 or exit_range.is_top


# =============================================================================
# SOUNDNESS ISSUE TESTS (from review trio)
# These tests verify potential soundness bugs identified by reviewers.
# =============================================================================


def test_soundness_literal_not_normalized_to_signed():
    """
    Soundness issue: Literals >= 2^255 not normalized to signed representation.

    The value 2^255 should be SIGNED_MIN (-2^255) in signed representation.
    When comparing SIGNED_MAX vs 2^255:
    - slt(SIGNED_MAX, 2^255) should be 0 because SIGNED_MAX > SIGNED_MIN
    - But if 2^255 is not normalized, the analysis may think 2^255 is positive
    """

    # 2^255 as a literal (this is SIGNED_MIN in signed representation)
    val_2_255 = 2**255

    analysis, fn = _analyze(
        f"""
        function test {{
        entry:
            %x = {SIGNED_MAX}
            %cmp = slt %x, {val_2_255}
            stop
        }}
        """
    )

    entry = fn.get_basic_block("entry")
    cmp_inst = entry.instructions[1]
    rng = analysis.get_range(cmp_inst.output, entry.instructions[-1])

    # SIGNED_MAX > SIGNED_MIN, so slt should return 0
    # If the literal 2^255 is not normalized, the analysis might wrongly return 1
    assert rng.lo == 0 and rng.hi == 0, (
        f"Expected slt(SIGNED_MAX, 2^255) = {{0}}, got {rng}. "
        f"2^255 should be normalized to SIGNED_MIN (-2^255) in signed representation."
    )


def test_soundness_literal_not_normalized_sgt():
    """
    Soundness issue: Literals >= 2^255 not normalized - sgt variant.

    sgt(SIGNED_MAX, 2^255) should be 1 because SIGNED_MAX > SIGNED_MIN.
    """
    from vyper.venom.analysis.variable_range.value_range import SIGNED_MAX

    val_2_255 = 2**255

    analysis, fn = _analyze(
        f"""
        function test {{
        entry:
            %x = {SIGNED_MAX}
            %cmp = sgt %x, {val_2_255}
            stop
        }}
        """
    )

    entry = fn.get_basic_block("entry")
    cmp_inst = entry.instructions[1]
    rng = analysis.get_range(cmp_inst.output, entry.instructions[-1])

    # SIGNED_MAX > SIGNED_MIN, so sgt should return 1
    assert rng.lo == 1 and rng.hi == 1, (
        f"Expected sgt(SIGNED_MAX, 2^255) = {{1}}, got {rng}. "
        f"2^255 should be normalized to SIGNED_MIN."
    )


def test_soundness_eq_literal_at_sign_boundary():
    """
    Soundness issue: eq with literal at sign boundary.

    eq(-1, UNSIGNED_MAX) should be 1 because they're the same bit pattern.
    """
    from vyper.venom.analysis.variable_range.value_range import UNSIGNED_MAX

    analysis, fn = _analyze(
        f"""
        function test {{
        entry:
            %x = -1
            %cmp = eq %x, {UNSIGNED_MAX}
            stop
        }}
        """
    )

    entry = fn.get_basic_block("entry")
    cmp_inst = entry.instructions[1]
    rng = analysis.get_range(cmp_inst.output, entry.instructions[-1])

    # -1 and UNSIGNED_MAX are the same 256-bit value
    assert rng.lo == 1 and rng.hi == 1, (
        f"Expected eq(-1, UNSIGNED_MAX) = {{1}}, got {rng}. " f"Both values are 0xFF...FF."
    )


def test_soundness_add_overflow_to_signed_boundary():
    """
    Soundness issue: Add evaluator doesn't check for signed overflow.

    add([0, 2^254], [0, 2^254]) could produce values up to 2^255.
    But 2^255 is SIGNED_MIN (negative), so the result range crosses
    the sign boundary. The analysis should return TOP, not [0, 2^255].
    """
    from vyper.venom.analysis.variable_range.value_range import SIGNED_MAX

    # Create two ranges [0, 2^254] and add them
    bound = 2**254

    analysis, fn = _analyze(
        f"""
        function test {{
        entry:
            %raw1 = calldataload 0
            %raw2 = calldataload 32
            %x = mod %raw1, {bound + 1}
            %y = mod %raw2, {bound + 1}
            %z = add %x, %y
            stop
        }}
        """
    )

    entry = fn.get_basic_block("entry")
    add_inst = next(inst for inst in entry.instructions if inst.opcode == "add")
    rng = analysis.get_range(add_inst.output, entry.instructions[-1])

    # x in [0, 2^254], y in [0, 2^254]
    # x + y could be up to 2^255 which is SIGNED_MIN (negative)
    # So the result crosses the sign boundary and should be TOP
    # If not TOP, at minimum the range should not claim to be non-negative
    if not rng.is_top:
        # If we get a concrete range, it's a soundness bug if hi > SIGNED_MAX
        # because that means values SIGNED_MAX+1 to hi are actually negative
        assert rng.hi <= SIGNED_MAX, (
            f"Soundness bug: add result range {rng} has hi > SIGNED_MAX. "
            f"Values above SIGNED_MAX are negative in signed representation. "
            f"Expected TOP or range with hi <= SIGNED_MAX."
        )


def test_soundness_mul_overflow_to_signed_boundary():
    """
    Soundness issue: Mul evaluator doesn't check for signed overflow.

    Similar to add - if multiplication result exceeds SIGNED_MAX,
    the high values are actually negative.
    """
    from vyper.venom.analysis.variable_range.value_range import SIGNED_MAX

    # Create a range that when squared exceeds SIGNED_MAX but not UNSIGNED_MAX
    # sqrt(SIGNED_MAX) ~ 2^127.5, so [0, 2^128] * [0, 2^128] can exceed SIGNED_MAX
    bound = 2**128

    analysis, fn = _analyze(
        f"""
        function test {{
        entry:
            %raw1 = calldataload 0
            %raw2 = calldataload 32
            %x = mod %raw1, {bound + 1}
            %y = mod %raw2, {bound + 1}
            %z = mul %x, %y
            stop
        }}
        """
    )

    entry = fn.get_basic_block("entry")
    mul_inst = next(inst for inst in entry.instructions if inst.opcode == "mul")
    rng = analysis.get_range(mul_inst.output, entry.instructions[-1])

    # Similar logic to add - result should be TOP or bounded by SIGNED_MAX
    if not rng.is_top:
        assert rng.hi <= SIGNED_MAX, (
            f"Soundness bug: mul result range {rng} has hi > SIGNED_MAX. "
            f"Expected TOP or range with hi <= SIGNED_MAX."
        )


def test_soundness_operand_range_normalizes_large_literal():
    """
    Test that _operand_range normalizes literals >= 2^255.

    When we have a literal like 2^255 + 100, it should be treated as
    SIGNED_MIN + 100 = -2^255 + 100 in signed representation.
    """
    from vyper.venom.analysis.variable_range.value_range import SIGNED_MIN

    # 2^255 + 100 should be SIGNED_MIN + 100
    large_val = 2**255 + 100
    expected_signed = SIGNED_MIN + 100

    analysis, fn = _analyze(
        f"""
        function test {{
        entry:
            %x = {large_val}
            %y = add %x, 0
            stop
        }}
        """
    )

    entry = fn.get_basic_block("entry")
    x_var = entry.instructions[0].output
    # Get range at the add instruction (after assignment)
    add_inst = entry.instructions[1]
    rng = analysis.get_range(x_var, add_inst)

    # The literal should be normalized to signed representation
    assert rng.is_constant, f"Expected constant range, got {rng}"
    assert rng.lo == expected_signed, (
        f"Expected literal {large_val} to be normalized to {expected_signed}, " f"got {rng.lo}"
    )


def test_soundness_add_result_range_validity():
    """
    Verify that add result ranges are valid (lo <= hi in signed representation).

    If add produces a range like [0, 2^255], this is invalid because:
    - 0 is non-negative
    - 2^255 is SIGNED_MIN (negative)
    - So lo > hi in signed terms, which is BOTTOM, not a valid range
    """
    from vyper.venom.analysis.variable_range.value_range import SIGNED_MAX

    # Use smaller bounds that definitely fit in RANGE_WIDTH_LIMIT
    # but could still overflow SIGNED_MAX when added
    bound = 2**127  # Well under RANGE_WIDTH_LIMIT

    analysis, fn = _analyze(
        f"""
        function test {{
        entry:
            %raw1 = calldataload 0
            %raw2 = calldataload 32
            %x = mod %raw1, {bound}
            %y = mod %raw2, {bound}
            %z = add %x, %y
            stop
        }}
        """
    )

    entry = fn.get_basic_block("entry")
    add_inst = next(inst for inst in entry.instructions if inst.opcode == "add")
    rng = analysis.get_range(add_inst.output, entry.instructions[-1])

    # Check range validity
    if not rng.is_top and not rng.is_empty:
        # In a valid range, lo <= hi
        assert rng.lo <= rng.hi, (
            f"Invalid range: lo={rng.lo} > hi={rng.hi}. "
            f"This indicates sign boundary crossing without returning TOP."
        )
        # Additionally, if lo >= 0 (non-negative range), hi should be <= SIGNED_MAX
        if rng.lo >= 0:
            assert rng.hi <= SIGNED_MAX, (
                f"Soundness bug: non-negative range {rng} has hi > SIGNED_MAX. "
                f"Values > SIGNED_MAX are negative."
            )


# =============================================================================
# SDIV AND SMOD TESTS
# =============================================================================


def test_sdiv_positive_range():
    """Test sdiv with a positive range dividend."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = mod %raw, 100
            %y = sdiv %x, 10
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    sdiv_inst = next(inst for inst in entry.instructions if inst.opcode == "sdiv")
    rng = analysis.get_range(sdiv_inst.output, entry.instructions[-1])
    # x in [0, 99], y = x / 10, so y in [0, 9]
    assert rng.lo == 0 and rng.hi == 9


def test_sdiv_negative_range():
    """Test sdiv with a negative range dividend."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %pos = mod %raw, 100
            %x = sub 0, %pos
            %y = sdiv %x, 10
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    sdiv_inst = next(inst for inst in entry.instructions if inst.opcode == "sdiv")
    rng = analysis.get_range(sdiv_inst.output, entry.instructions[-1])
    # x in [-99, 0], y = x / 10, so y in [-9, 0] (truncation toward zero)
    assert rng.lo == -9 and rng.hi == 0


def test_sdiv_spanning_zero():
    """Test sdiv with a range spanning zero."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = signextend 0, %raw
            %y = sdiv %x, 10
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    sdiv_inst = next(inst for inst in entry.instructions if inst.opcode == "sdiv")
    rng = analysis.get_range(sdiv_inst.output, entry.instructions[-1])
    # x in [-128, 127], y = x / 10, so y in [-12, 12]
    assert rng.lo == -12 and rng.hi == 12


def test_sdiv_by_zero():
    """Test sdiv by zero returns 0 (EVM spec)."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = mod %raw, 100
            %y = sdiv %x, 0
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    sdiv_inst = next(inst for inst in entry.instructions if inst.opcode == "sdiv")
    rng = analysis.get_range(sdiv_inst.output, entry.instructions[-1])
    assert rng.lo == 0 and rng.hi == 0


def test_sdiv_negative_divisor_returns_top():
    """Test sdiv with negative divisor returns TOP (conservative)."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = mod %raw, 100
            %y = sdiv %x, -10
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    sdiv_inst = next(inst for inst in entry.instructions if inst.opcode == "sdiv")
    rng = analysis.get_range(sdiv_inst.output, entry.instructions[-1])
    # Currently returns TOP for negative divisors
    assert rng.is_top


def test_smod_positive_dividend():
    """Test smod with positive dividend range."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = mod %raw, 6
            %y = smod %x, 10
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    smod_inst = next(inst for inst in entry.instructions if inst.opcode == "smod")
    rng = analysis.get_range(smod_inst.output, entry.instructions[-1])
    # x in [0, 5], divisor = 10, result in [0, 5]
    assert rng.lo == 0 and rng.hi == 5


def test_smod_nonpositive_range():
    """Test smod with non-positive dividend range (including zero)."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %pos = mod %raw, 6
            %x = sub 0, %pos
            %y = smod %x, 10
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    smod_inst = next(inst for inst in entry.instructions if inst.opcode == "smod")
    rng = analysis.get_range(smod_inst.output, entry.instructions[-1])
    # x in [-5, 0], divisor = 10, result in [-5, 0]
    assert rng.lo == -5 and rng.hi == 0


def test_smod_spanning_zero():
    """Test smod with dividend range spanning zero."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = signextend 0, %raw
            %y = smod %x, 10
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    smod_inst = next(inst for inst in entry.instructions if inst.opcode == "smod")
    rng = analysis.get_range(smod_inst.output, entry.instructions[-1])
    # x in [-128, 127], divisor = 10, result in [-9, 9]
    assert rng.lo == -9 and rng.hi == 9


def test_smod_by_zero():
    """Test smod by zero returns 0 (EVM spec)."""
    analysis, fn = _analyze(
        """
        function test {
        entry:
            %raw = calldataload 0
            %x = mod %raw, 100
            %y = smod %x, 0
            stop
        }
        """
    )

    entry = fn.get_basic_block("entry")
    smod_inst = next(inst for inst in entry.instructions if inst.opcode == "smod")
    rng = analysis.get_range(smod_inst.output, entry.instructions[-1])
    assert rng.lo == 0 and rng.hi == 0
