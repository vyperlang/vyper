import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import AlgebraicOptimizationPass, AssignElimination

"""
Test abstract binop+unop optimizations in algebraic optimizations pass
"""

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([AssignElimination, AlgebraicOptimizationPass, AssignElimination])


def test_sccp_algebraic_opt_sub_xor():
    # x - x -> 0
    # x ^ x -> 0
    pre = """
    _global:
        %par = source
        %1 = sub %par, %par
        %2 = xor %par, %par
        sink %1, %2
    """
    post = """
    _global:
        %par = source
        sink 0, 0
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_zero_sub_add_xor():
    # x + 0 == x - 0 == x ^ 0 -> x
    # (this cannot be done for 0 - x)
    pre = """
    _global:
        %par = source
        %1 = sub %par, 0
        %2 = xor %par, 0
        %3 = add %par, 0
        %4 = sub 0, %par
        %5 = add 0, %par
        %6 = xor 0, %par
        sink %1, %2, %3, %4, %5, %6
    """
    post = """
    _global:
        %par = source
        %4 = sub 0, %par
        sink %par, %par, %par, %4, %par, %par
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_sub_xor_max():
    # x ^ 0xFF..FF -> not x
    # -1 - x -> ~x
    pre = """
    _global:
        %par = source
        %tmp = -1
        %1 = xor -1, %par
        %2 = xor %par, -1

        %3 = sub -1, %par

        sink %1, %2, %3
    """
    post = """
    _global:
        %par = source
        %1 = not %par
        %2 = not %par
        %3 = not %par
        sink %1, %2, %3
    """

    # hevm chokes on this example.
    _check_pre_post(pre, post, hevm=False)


def test_sccp_algebraic_opt_shift():
    # x << 0 == x >> 0 == x (sar) 0 -> x
    # sar is right arithmetic shift
    pre = """
    _global:
        %par = source
        %1 = shl 0, %par
        %2 = shr 0, %1
        %3 = sar 0, %2
        sink %1, %2, %3
    """
    post = """
    _global:
        %par = source
        sink %par, %par, %par
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("opcode", ("mul", "and", "div", "sdiv", "mod", "smod"))
def test_mul_by_zero(opcode):
    # x * 0 == 0 * x == x % 0 == 0 % x == x // 0 == 0 // x == x & 0 == 0 & x -> 0
    pre = f"""
    _global:
        %par = source
        %1 = {opcode} 0, %par
        %2 = {opcode} %par, 0
        sink %1, %2
    """
    post = """
    _global:
        %par = source
        sink 0, 0
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_multi_neutral_elem():
    # x * 1 == 1 * x == x / 1 -> x
    # checks for non comutative ops
    pre = """
    _global:
        %par = source
        %1_1 = mul 1, %par
        %1_2 = mul %par, 1
        %2_1 = div 1, %par
        %2_2 = div %par, 1
        %3_1 = sdiv 1, %par
        %3_2 = sdiv %par, 1
        sink %1_1, %1_2, %2_1, %2_2, %3_1, %3_2
    """
    post = """
    _global:
        %par = source
        %2_1 = div 1, %par
        %3_1 = sdiv 1, %par
        sink %par, %par, %2_1, %par, %3_1, %par
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_mod_zero():
    # x % 1 -> 0
    pre = """
    _global:
        %par = source
        %1 = mod %par, 1
        %2 = smod %par, 1
        sink %1, %2
    """
    post = """
    _global:
        %par = source
        sink 0, 0
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_and_max():
    # x & 0xFF..FF == 0xFF..FF & x -> x
    max_uint256 = 2**256 - 1
    pre = f"""
    _global:
        %par = source
        %tmp = {max_uint256}
        %1 = and %par, %tmp
        %2 = and %tmp, %par
        sink %1, %2
    """
    post = """
    _global:
        %par = source
        sink %par, %par
    """

    _check_pre_post(pre, post)


# test powers of 2 from n==2 to n==255.
# (skip 1 since there are specialized rules for n==1)
@pytest.mark.parametrize("n", range(2, 256))
def test_sccp_algebraic_opt_mul_div_to_shifts(n):
    # x * 2**n -> x << n
    # x / 2**n -> x >> n
    y = 2**n
    pre = f"""
    _global:
        %par = source
        %1 = mul %par, {y}
        %2 = mod %par, {y}
        %3 = div %par, {y}
        %4 = mul {y}, %par
        %5 = mod {y}, %par ; note: this is blocked!
        %6 = div {y}, %par ; blocked!
        sink %1, %2, %3, %4, %5, %6
    """
    post = f"""
    _global:
        %par = source
        %1 = shl {n}, %par
        %2 = and {y - 1}, %par
        %3 = shr {n}, %par
        %4 = shl {n}, %par
        %5 = mod {y}, %par
        %6 = div {y}, %par
        sink %1, %2, %3, %4, %5, %6
    """

    _check_pre_post(pre, post, hevm=False)


def test_sccp_algebraic_opt_exp():
    # x ** 0 == 0 ** x -> 1
    # x ** 1 -> x
    pre = """
    _global:
        %par = source
        %1 = exp %par, 0
        %2 = exp 1, %par
        %3 = exp 0, %par
        %4 = exp %par, 1
        sink %1, %2, %3, %4
    """
    post = """
    _global:
        %par = source
        %3 = iszero %par
        sink 1, 1, %3, %par
    """

    # can set hevm=True after https://github.com/ethereum/hevm/pull/638 is merged
    _check_pre_post(pre, post, hevm=False)


def test_sccp_algebraic_opt_compare_self():
    # x < x == x > x -> 0
    pre = """
    _global:
        %par = source
        %tmp = %par
        %1 = gt %tmp, %par
        %2 = sgt %tmp, %par
        %3 = lt %tmp, %par
        %4 = slt %tmp, %par
        sink %1, %2, %3, %4
    """
    post = """
    _global:
        %par = source
        sink 0, 0, 0, 0
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_or():
    # x | 0 -> x
    # x | 0xFF..FF -> 0xFF..FF
    max_uint256 = 2**256 - 1
    pre = f"""
    _global:
        %par = source
        %1 = or %par, 0
        %2 = or %par, {max_uint256}
        %3 = or 0, %par
        %4 = or {max_uint256}, %par
        sink %1, %2, %3, %4
    """
    post = f"""
    _global:
        %par = source
        sink %par, {max_uint256}, %par, {max_uint256}
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_eq():
    # (x == 0) == (0 == x) -> iszero x
    # x == x -> 1
    # x == 0xFFFF..FF -> iszero(not x)
    pre = """
    global:
        %par = source
        %1 = eq %par, 0
        %2 = eq 0, %par

        %3 = eq %par, -1
        %4 = eq -1, %par

        %5 = eq %par, %par
        sink %1, %2, %3, %4, %5
    """
    post = """
    global:
        %par = source
        %1 = iszero %par
        %2 = iszero %par
        %6 = not %par
        %3 = iszero %6
        %7 = not %par
        %4 = iszero %7
        sink %1, %2, %3, %4, 1
    """
    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_boolean_or():
    # x | (non zero) -> 1 if it is only used as boolean
    some_nonzero = 123
    pre = f"""
    _global:
        %par = source
        %1 = or %par, {some_nonzero}
        %2 = or %par, {some_nonzero}
        assert %1
        %3 = or {some_nonzero}, %par
        %4 = or {some_nonzero}, %par
        assert %3
        sink %2, %4
    """
    post = f"""
    _global:
        %par = source
        %2 = or {some_nonzero}, %par
        assert 1
        %4 = or {some_nonzero}, %par
        assert 1
        sink %2, %4
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_boolean_eq():
    # x == y -> iszero (x ^ y) if it is only used as boolean
    pre = """
    _global:
        %par = source
        %par2 = source
        %1 = eq %par, %par2
        %2 = eq %par, %par2
        assert %1
        sink %2
    """
    post = """
    _global:
        %par = source
        %par2 = source
        %3 = xor %par, %par2
        %1 = iszero %3
        %2 = eq %par, %par2
        assert %1
        sink %2
    """

    _check_pre_post(pre, post)


def test_compare_never():
    # unsigned x > 0xFF..FF == x < 0 -> 0
    # signed: x > MAX_SIGNED (0x3F..FF) == x < MIN_SIGNED (0xF0..00) -> 0
    min_int256 = -(2**255)
    max_int256 = 2**255 - 1
    min_uint256 = 0
    max_uint256 = 2**256 - 1
    pre = f"""
    _global:
        %par = source

        %1 = slt %par, {min_int256}
        %2 = sgt %par, {max_int256}
        %3 = lt %par, {min_uint256}
        %4 = gt %par, {max_uint256}

        sink %1, %2, %3, %4
    """
    post = """
    _global:
        %par = source
        sink 0, 0, 0, 0
    """

    _check_pre_post(pre, post)


def test_comparison_zero():
    # x > 0 => iszero(iszero x)
    # 0 < x => iszero(iszero x)
    pre = """
    _global:
        %par = source
        %1 = lt 0, %par
        %2 = gt %par, 0
        sink %1, %2
    """
    post = """
    _global:
        %par = source
        %3 = iszero %par
        %1 = iszero %3
        %4 = iszero %par
        %2 = iszero %4
        sink %1, %2
    """

    _check_pre_post(pre, post)


def test_comparison_almost_never():
    # unsigned:
    #   x < 1 => eq x 0 => iszero x
    #   MAX_UINT - 1 < x => eq x MAX_UINT => iszero(not x)
    # signed
    #   x < MIN_INT + 1 => eq x MIN_INT
    #   MAX_INT - 1 < x => eq x MAX_INT

    max_uint256 = 2**256 - 1
    max_int256 = 2**255 - 1
    min_int256 = -(2**255)
    pre1 = f"""
    _global:
        %par = source
        %1 = lt %par, 1
        %2 = gt %par, {max_uint256 - 1}
        %3 = sgt %par, {max_int256 - 1}
        %4 = slt %par, {min_int256 + 1}

        sink %1, %2, %3, %4
    """
    # commuted versions - produce same output
    pre2 = f"""
    _global:
        %par = source
        %1 = gt 1, %par
        %2 = lt {max_uint256 - 1}, %par
        %3 = slt {max_int256 - 1}, %par
        %4 = sgt {min_int256 + 1}, %par
        sink %1, %2, %3, %4
    """
    post = f"""
    _global:
        %par = source
        ; lt %par, 1 => eq 0, %par => iszero %par
        %1 = iszero %par
        ; x > MAX_UINT256 - 1 => eq MAX_UINT x => iszero(not x)
        %5 = not %par
        %2 = iszero %5
        %3 = eq {max_int256}, %par
        %4 = eq {min_int256}, %par
        sink %1, %2, %3, %4
    """

    _check_pre_post(pre1, post)
    _check_pre_post(pre2, post)


def test_comparison_almost_always():
    # unsigned
    #   x > 0 => iszero(iszero x)
    #   0 < x => iszero(iszero x)
    #   x < MAX_UINT => iszero(eq x MAX_UINT) => iszero(iszero(not x))
    # signed
    #   x < MAX_INT => iszero(eq MAX_INT) => iszero(iszero(xor MAX_INT x))

    max_uint256 = 2**256 - 1
    max_int256 = 2**255 - 1
    min_int256 = -(2**255)

    pre1 = f"""
    _global:
        %par = source
        %1 = gt %par, 0
        %2 = lt %par, {max_uint256}
        assert %2
        %3 = slt %par, {max_int256}
        assert %3
        %4 = sgt %par, {min_int256}
        assert %4
        sink %1
    """
    # commuted versions
    pre2 = f"""
    _global:
        %par = source
        %1 = lt 0, %par
        %2 = gt {max_uint256}, %par
        assert %2
        %3 = sgt {max_int256}, %par
        assert %3
        %4 = slt {min_int256}, %par
        assert %4
        sink %1
    """
    post = f"""
    _global:
        %par = source
        %5 = iszero %par
        %1 = iszero %5
        %6 = not %par
        %7 = iszero %6
        %2 = iszero %7
        assert %2
        %8 = xor %par, {max_int256}
        %9 = iszero %8
        %3 = iszero %9
        assert %3
        %10 = xor %par, {min_int256}
        %11 = iszero %10
        %4 = iszero %11
        assert %4
        sink %1
    """

    _check_pre_post(pre1, post)
    _check_pre_post(pre2, post)


@pytest.mark.parametrize("val", (100, 2, 3, -100))
def test_comparison_ge_le(val):
    # iszero(x < 100) => 99 < x
    # iszero(x > 100) => 101 > x

    up = val + 1
    down = val - 1

    abs_val = abs(val)
    abs_up = abs_val + 1
    abs_down = abs_val - 1

    pre1 = f"""
    _global:
        %par = source
        %1 = lt %par, {abs_val}
        %3 = gt %par, {abs_val}
        %2 = iszero %1
        %4 = iszero %3
        %5 = slt %par, {val}
        %7 = sgt %par, {val}
        %6 = iszero %5
        %8 = iszero %7
        sink %2, %4, %6, %8
    """
    pre2 = f"""
    _global:
        %par = source
        %1 = gt {abs_val}, %par
        %3 = lt {abs_val}, %par
        %2 = iszero %1
        %4 = iszero %3
        %5 = sgt {val}, %par
        %7 = slt {val}, %par
        %6 = iszero %5
        %8 = iszero %7
        sink %2, %4, %6, %8
    """
    post = f"""
    _global:
        %par = source
        %1 = lt {abs_down}, %par
        %3 = gt {abs_up}, %par
        %5 = slt {down}, %par
        %7 = sgt {up}, %par
        sink %1, %3, %5, %7
    """

    _check_pre_post(pre1, post)
    _check_pre_post(pre2, post)


def test_signextend_range_elimination():
    # When value is already in valid signed range, signextend is no-op
    # %x = and %input, 0x7F gives range [0, 127] which is valid for int8
    pre = """
    _global:
        %input = source
        %x = and %input, 127
        %y = signextend 0, %x
        sink %y
    """
    # signextend(0, %x) should be eliminated since %x is in [-128, 127]
    # Note: and operands get flipped (literal first)
    post = """
    _global:
        %input = source
        %x = and 127, %input
        sink %x
    """
    _check_pre_post(pre, post)


def test_signextend_range_no_elimination():
    # When value might be outside valid signed range, signextend is kept
    # %x = and %input, 0xFF gives range [0, 255] which exceeds int8 max (127)
    pre = """
    _global:
        %input = source
        %x = and %input, 255
        %y = signextend 0, %x
        sink %y
    """
    # signextend should NOT be eliminated since %x can be > 127
    # Note: and operands get flipped (literal first)
    post = """
    _global:
        %input = source
        %x = and 255, %input
        %y = signextend 0, %x
        sink %y
    """
    _check_pre_post(pre, post)


def test_signextend_unwrapped_zero_byte_index_not_eliminated():
    # 2**256 wraps to byte index 0. It must not take the raw n >= 31 no-op path.
    zero_mod_uint256 = 2**256
    pre = f"""
    _global:
        %x = source
        %y = signextend {zero_mod_uint256}, %x
        sink %y
    """
    post = f"""
    _global:
        %x = source
        %y = signextend {zero_mod_uint256}, %x
        sink %y
    """
    _check_pre_post(pre, post, hevm=False)


def test_signextend_chain_uses_wrapped_byte_indexes():
    # The outer index wraps to 0, so it is not wider than the inner index 1.
    zero_mod_uint256 = 2**256
    pre = f"""
    _global:
        %x = source
        %inner = signextend 1, %x
        %outer = signextend {zero_mod_uint256}, %inner
        sink %outer
    """
    post = f"""
    _global:
        %x = source
        %inner = signextend 1, %x
        %outer = signextend {zero_mod_uint256}, %inner
        sink %outer
    """
    _check_pre_post(pre, post, hevm=False)


@pytest.mark.skip(reason="Range-based comparison needs investigation - flip timing issue")
def test_comparison_range_always_true():
    # When range proves comparison is always true
    # mod gives range [0, N-1], so gt N, x (N > x) is always true
    # since x is at most N-1, and N > N-1
    pre = """
    _global:
        %input = source
        %x = mod %input, 100
        %y = gt 100, %x
        sink %y
    """
    post = """
    _global:
        %input = source
        %x = mod %input, 100
        sink 1
    """
    _check_pre_post(pre, post)


def test_comparison_range_always_false():
    # When range proves comparison is always false
    # mod gives range [0, N-1], so lt 0, x (0 < x) is false when x can be 0
    # Better: gt 0, x (0 > x) is always false since x >= 0
    pre = """
    _global:
        %input = source
        %x = mod %input, 100
        %y = gt 0, %x
        sink %y
    """
    post = """
    _global:
        %input = source
        %x = mod %input, 100
        sink 0
    """
    _check_pre_post(pre, post)


def test_signed_comparison_range_past_signed_max_not_folded():
    # and gives %a the range [0, 2**255]. The word 2**255 is MIN_INT256,
    # so slt %a, 0 is 1 for that input and neither comparison may fold.
    pre = f"""
    _global:
        %x = source
        %a = and %x, {2**255}
        %c = slt %a, 0
        %d = lt %c, 1
        sink %d
    """
    post = f"""
    _global:
        %x = source
        %a = and {2**255}, %x
        %c = sgt 0, %a
        %d = iszero %c
        sink %d
    """
    _check_pre_post(pre, post)


# Comparison folding via range analysis, both operands variables.
#
# Operand definitions shared by the tests below; each one defines %a
# (from %x) or %b (from %y) with the value range given in its name, as a
# (definition, definition after operand canonicalization) pair.
_A_IN_0_99 = ("%a = and %x, 99", "%a = and 99, %x")
_A_IN_0_100 = ("%a = and %x, 100", "%a = and 100, %x")
_A_IN_100_200 = (
    """%a_base = and %x, 100
        %a = add %a_base, 100""",
    """%a_base = and 100, %x
        %a = add 100, %a_base""",
)
_A_IN_NEG100_NEG1 = (
    """%a_base = and %x, 99
        %a = sub %a_base, 100""",
    """%a_base = and 99, %x
        %a = sub %a_base, 100""",
)
_B_IN_0_99 = ("%b = and %y, 99", "%b = and 99, %y")
_B_IN_0_100 = ("%b = and %y, 100", "%b = and 100, %y")
_B_IN_100_200 = (
    """%b_base = and %y, 100
        %b = add %b_base, 100""",
    """%b_base = and 100, %y
        %b = add 100, %b_base""",
)


@pytest.mark.parametrize(
    "opcode,a_def,b_def,expected",
    [
        pytest.param("lt", _A_IN_0_99, _B_IN_100_200, 1, id="lt-a-below-b"),
        pytest.param("lt", _A_IN_100_200, _B_IN_0_99, 0, id="lt-a-above-b"),
        pytest.param("gt", _A_IN_100_200, _B_IN_0_99, 1, id="gt-a-above-b"),
        pytest.param("gt", _A_IN_0_99, _B_IN_100_200, 0, id="gt-a-below-b"),
        # ranges meeting at a single value still decide a strict comparison
        pytest.param("lt", _A_IN_100_200, _B_IN_0_100, 0, id="lt-a-lo-meets-b-hi"),
        pytest.param("gt", _A_IN_0_100, _B_IN_100_200, 0, id="gt-a-hi-meets-b-lo"),
        pytest.param("slt", _A_IN_0_99, _B_IN_100_200, 1, id="slt-a-below-b"),
        pytest.param("sgt", _A_IN_100_200, _B_IN_0_99, 1, id="sgt-a-above-b"),
        # [-100, -1] is [2**256 - 100, 2**256 - 1] as unsigned words, so it
        # is above any non-negative range in an unsigned comparison
        pytest.param("gt", _A_IN_NEG100_NEG1, _B_IN_0_99, 1, id="gt-negative-a-is-large-unsigned"),
        pytest.param("lt", _A_IN_NEG100_NEG1, _B_IN_0_99, 0, id="lt-negative-a-is-large-unsigned"),
        # as signed values, [-100, -1] is below any non-negative range
        pytest.param("slt", _A_IN_NEG100_NEG1, _B_IN_0_99, 1, id="slt-negative-a-below-b"),
    ],
)
def test_comparison_disjoint_ranges_fold(opcode, a_def, b_def, expected):
    # the operand ranges do not overlap, so the comparison is decided and
    # its result is sunk directly; the operand definitions stay as dead code
    a_pre, a_post = a_def
    b_pre, b_post = b_def
    pre = f"""
    _global:
        %x = source
        %y = source
        {a_pre}
        {b_pre}
        %cmp = {opcode} %a, %b
        sink %cmp
    """
    post = f"""
    _global:
        %x = source
        %y = source
        {a_post}
        {b_post}
        sink {expected}
    """
    _check_pre_post(pre, post)


def test_lt_var_var_overlapping_no_fold():
    """
    lt a, b where ranges overlap → cannot fold
    a ∈ [0, 255], b ∈ [100, 200] → overlap at [100, 200]
    """
    pre = """
    _global:
        %x = source
        %y = source
        %a = and %x, 255
        %b_base = and %y, 100
        %b = add %b_base, 100
        %cmp = lt %a, %b
        sink %cmp
    """

    # Should remain unchanged (comparison not folded)
    # Note: operands get canonicalized (literal first for commutative ops)
    post = """
    _global:
        %x = source
        %y = source
        %a = and 255, %x
        %b_base = and 100, %y
        %b = add 100, %b_base
        %cmp = lt %a, %b
        sink %cmp
    """

    _check_pre_post(pre, post)


def test_gt_var_var_unknown_range_no_fold():
    """
    gt a, b where one operand has unknown range → cannot fold
    """
    pre = """
    _global:
        %a = source
        %y = source
        %b = and %y, 99
        %cmp = gt %a, %b
        sink %cmp
    """

    # Should remain unchanged - %a has TOP range
    # Note: operands get canonicalized
    post = """
    _global:
        %a = source
        %y = source
        %b = and 99, %y
        %cmp = gt %a, %b
        sink %cmp
    """

    _check_pre_post(pre, post)


def test_lt_modulo_result_always_bounded():
    """
    After modulo, result is always less than the divisor.
    a = x % 100 → a ∈ [0, 99]
    b = y % 1000 + 100 → b ∈ [100, 1099]
    lt a, b → always true
    """
    pre = """
    _global:
        %x = source
        %y = source
        %a = mod %x, 100
        %b_mod = mod %y, 1000
        %b = add %b_mod, 100
        %cmp = lt %a, %b
        sink %cmp
    """

    post = """
    _global:
        %x = source
        %y = source
        %a = mod %x, 100
        %b_mod = mod %y, 1000
        %b = add 100, %b_mod
        sink 1
    """

    _check_pre_post(pre, post)


def test_slt_var_var_signed_wrap_no_fold():
    """
    slt a, b where a's range includes 2**255 (SIGNED_MIN) must not fold.
    a ∈ [0, 2**255], b ∈ [0, 0] → signed comparison is not constant.
    """
    pre = """
    _global:
        %x = source
        %y = source
        %a = and %x, 0x8000000000000000000000000000000000000000000000000000000000000000
        %b = and %y, 0
        %cmp = slt %a, %b
        sink %cmp
    """

    # %b folds to 0 and is substituted, but %cmp must not fold due to
    # signed wraparound.
    post = """
    _global:
        %x = source
        %y = source
        %a = and 0x8000000000000000000000000000000000000000000000000000000000000000, %x
        %cmp = slt %a, 0
        sink %cmp
    """

    _check_pre_post(pre, post)


def test_assert_operand_folded_via_comparison():
    """
    The comparison folds to 1 and the assert consumes the literal directly.
    """
    pre = """
    _global:
        %x = source
        %y = source
        %a = and %x, 99
        %b_base = and %y, 100
        %b = add %b_base, 100
        %cmp = lt %a, %b
        assert %cmp
        sink %a
    """

    # Note: operands get canonicalized
    post = """
    _global:
        %x = source
        %y = source
        %a = and 99, %x
        %b_base = and 100, %y
        %b = add 100, %b_base
        assert 1
        sink %a
    """

    _check_pre_post(pre, post)


def test_lt_range_spans_boundary_from_nonneg_no_fold():
    """
    Range [0, 2^255] spans the unsigned boundary from the non-negative side.
    This should NOT fold because the range contains both small and large unsigned values.

    We construct this by having a range that could be 0 or 2^255.
    """
    pre = """
    _global:
        %x = source
        %y = source
        ; %a can be 0 or 2^255 (spans the boundary)
        %mask = and %x, 0x8000000000000000000000000000000000000000000000000000000000000000
        %a = or %mask, 0
        %b = and %y, 99
        %cmp = lt %a, %b
        sink %cmp
    """

    # Should NOT fold - %a's range spans the boundary
    # Note: or %mask, 0 simplifies to %mask, which is substituted into %cmp
    post = """
    _global:
        %x = source
        %y = source
        %mask = and 0x8000000000000000000000000000000000000000000000000000000000000000, %x
        %b = and 99, %y
        %cmp = lt %mask, %b
        sink %cmp
    """

    _check_pre_post(pre, post)


def test_gt_both_negative_ranges_disjoint():
    """
    Both operands are negative words, i.e. both lie in the high half of
    the unsigned space, so an unsigned comparison is decided by their
    signed order: a ∈ [-100, -1] is above b ∈ [-300, -201].
    """
    pre = """
    _global:
        %x = source
        %y = source
        %a_base = and %x, 99
        %a = sub %a_base, 100
        %b_base = and %y, 99
        %b = sub %b_base, 300
        %cmp = gt %a, %b
        sink %cmp
    """

    post = """
    _global:
        %x = source
        %y = source
        %a_base = and 99, %x
        %a = sub %a_base, 100
        %b_base = and 99, %y
        %b = sub %b_base, 300
        sink 1
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("opcode", ("slt", "sgt"))
def test_signed_comparison_second_operand_range_past_signed_max_no_fold(opcode):
    """
    b ∈ [0, 2**255] contains the word 2**255, which is MIN_INT256. With
    a ∈ [-100, -1] the raw bounds alone would order a below b, but for
    b = MIN_INT256 a is above b, so neither slt nor sgt may fold.
    """
    pre = f"""
    _global:
        %x = source
        %y = source
        %a_base = and %x, 99
        %a = sub %a_base, 100
        %b = and %y, {2**255}
        %cmp = {opcode} %a, %b
        sink %cmp
    """

    # Note: operands get canonicalized
    post = f"""
    _global:
        %x = source
        %y = source
        %a_base = and 99, %x
        %a = sub %a_base, 100
        %b = and {2**255}, %y
        %cmp = {opcode} %a, %b
        sink %cmp
    """

    _check_pre_post(pre, post)


def test_folded_comparison_feeds_second_comparison():
    """
    Range analysis evaluates %c1 = lt a, b to the constant 1 (a ∈ [0, 9],
    b ∈ [10, 99]), so the second comparison lt %c1, d with d ∈ [2, 99] is
    decided as well and both fold in the same run.
    """
    pre = """
    _global:
        %x = source
        %y = source
        %z = source
        %a = and %x, 9
        %b_base = and %y, 89
        %b = add %b_base, 10
        %c1 = lt %a, %b
        %d_base = and %z, 97
        %d = add %d_base, 2
        %c2 = lt %c1, %d
        sink %c2
    """

    post = """
    _global:
        %x = source
        %y = source
        %z = source
        %a = and 9, %x
        %b_base = and 89, %y
        %b = add 10, %b_base
        %d_base = and 97, %z
        %d = add 2, %d_base
        sink 1
    """

    _check_pre_post(pre, post)
