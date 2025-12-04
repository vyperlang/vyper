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
    assert large_range.lo >= 10


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
    x_var = fn.get_basic_block("entry").instructions[0].output

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
