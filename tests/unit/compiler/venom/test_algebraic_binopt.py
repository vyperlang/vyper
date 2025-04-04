import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import AlgebraicOptimizationPass, StoreElimination

"""
Test abstract binop+unop optimizations in algebraic optimizations pass
"""

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([StoreElimination, AlgebraicOptimizationPass, StoreElimination])


def test_sccp_algebraic_opt_sub_xor():
    # x - x -> 0
    # x ^ x -> 0
    pre = """
    _global:
        %par = param
        %1 = sub %par, %par
        %2 = xor %par, %par
        sink %1, %2
    """
    post = """
    _global:
        %par = param
        sink 0, 0
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_zero_sub_add_xor():
    # x + 0 == x - 0 == x ^ 0 -> x
    # (this cannot be done for 0 - x)
    pre = """
    _global:
        %par = param
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
        %par = param
        %4 = sub 0, %par
        sink %par, %par, %par, %4, %par, %par
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_sub_xor_max():
    # x ^ 0xFF..FF -> not x
    # -1 - x -> ~x
    pre = """
    _global:
        %par = param
        %tmp = -1
        %1 = xor -1, %par
        %2 = xor %par, -1

        %3 = sub -1, %par

        sink %1, %2, %3
    """
    post = """
    _global:
        %par = param
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
        %par = param
        %1 = shl 0, %par
        %2 = shr 0, %1
        %3 = sar 0, %2
        sink %1, %2, %3
    """
    post = """
    _global:
        %par = param
        sink %par, %par, %par
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("opcode", ("mul", "and", "div", "sdiv", "mod", "smod"))
def test_mul_by_zero(opcode):
    # x * 0 == 0 * x == x % 0 == 0 % x == x // 0 == 0 // x == x & 0 == 0 & x -> 0
    pre = f"""
    _global:
        %par = param
        %1 = {opcode} 0, %par
        %2 = {opcode} %par, 0
        sink %1, %2
    """
    post = """
    _global:
        %par = param
        sink 0, 0
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_multi_neutral_elem():
    # x * 1 == 1 * x == x / 1 -> x
    # checks for non comutative ops
    pre = """
    _global:
        %par = param
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
        %par = param
        %2_1 = div 1, %par
        %3_1 = sdiv 1, %par
        sink %par, %par, %2_1, %par, %3_1, %par
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_mod_zero():
    # x % 1 -> 0
    pre = """
    _global:
        %par = param
        %1 = mod %par, 1
        %2 = smod %par, 1
        sink %1, %2
    """
    post = """
    _global:
        %par = param
        sink 0, 0
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_and_max():
    # x & 0xFF..FF == 0xFF..FF & x -> x
    max_uint256 = 2**256 - 1
    pre = f"""
    _global:
        %par = param
        %tmp = {max_uint256}
        %1 = and %par, %tmp
        %2 = and %tmp, %par
        sink %1, %2
    """
    post = """
    _global:
        %par = param
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
        %par = param
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
        %par = param
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
        %par = param
        %1 = exp %par, 0
        %2 = exp 1, %par
        %3 = exp 0, %par
        %4 = exp %par, 1
        sink %1, %2, %3, %4
    """
    post = """
    _global:
        %par = param
        %3 = iszero %par
        sink 1, 1, %3, %par
    """

    # can set hevm=True after https://github.com/ethereum/hevm/pull/638 is merged
    _check_pre_post(pre, post, hevm=False)


def test_sccp_algebraic_opt_compare_self():
    # x < x == x > x -> 0
    pre = """
    _global:
        %par = param
        %tmp = %par
        %1 = gt %tmp, %par
        %2 = sgt %tmp, %par
        %3 = lt %tmp, %par
        %4 = slt %tmp, %par
        sink %1, %2, %3, %4
    """
    post = """
    _global:
        %par = param
        sink 0, 0, 0, 0
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_or():
    # x | 0 -> x
    # x | 0xFF..FF -> 0xFF..FF
    max_uint256 = 2**256 - 1
    pre = f"""
    _global:
        %par = param
        %1 = or %par, 0
        %2 = or %par, {max_uint256}
        %3 = or 0, %par
        %4 = or {max_uint256}, %par
        sink %1, %2, %3, %4
    """
    post = f"""
    _global:
        %par = param
        sink %par, {max_uint256}, %par, {max_uint256}
    """

    _check_pre_post(pre, post)


def test_sccp_algebraic_opt_eq():
    # (x == 0) == (0 == x) -> iszero x
    # x == x -> 1
    # x == 0xFFFF..FF -> iszero(not x)
    pre = """
    global:
        %par = param
        %1 = eq %par, 0
        %2 = eq 0, %par

        %3 = eq %par, -1
        %4 = eq -1, %par

        %5 = eq %par, %par
        sink %1, %2, %3, %4, %5
    """
    post = """
    global:
        %par = param
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
        %par = param
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
        %par = param
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
        %par = param
        %par2 = param
        %1 = eq %par, %par2
        %2 = eq %par, %par2
        assert %1
        sink %2
    """
    post = """
    _global:
        %par = param
        %par2 = param
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
        %par = param

        %1 = slt %par, {min_int256}
        %2 = sgt %par, {max_int256}
        %3 = lt %par, {min_uint256}
        %4 = gt %par, {max_uint256}

        sink %1, %2, %3, %4
    """
    post = """
    _global:
        %par = param
        sink 0, 0, 0, 0
    """

    _check_pre_post(pre, post)


def test_comparison_zero():
    # x > 0 => iszero(iszero x)
    # 0 < x => iszero(iszero x)
    pre = """
    _global:
        %par = param
        %1 = lt 0, %par
        %2 = gt %par, 0
        sink %1, %2
    """
    post = """
    _global:
        %par = param
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
        %par = param
        %1 = lt %par, 1
        %2 = gt %par, {max_uint256 - 1}
        %3 = sgt %par, {max_int256 - 1}
        %4 = slt %par, {min_int256 + 1}

        sink %1, %2, %3, %4
    """
    # commuted versions - produce same output
    pre2 = f"""
    _global:
        %par = param
        %1 = gt 1, %par
        %2 = lt {max_uint256 - 1}, %par
        %3 = slt {max_int256 - 1}, %par
        %4 = sgt {min_int256 + 1}, %par
        sink %1, %2, %3, %4
    """
    post = f"""
    _global:
        %par = param
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
        %par = param
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
        %par = param
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
        %par = param
        %5 = iszero %par
        %1 = iszero %5
        %9 = not %par  ; (eq -1 x) => (iszero (not x))
        %6 = iszero %9
        %2 = iszero %6
        assert %2
        %10 = xor %par, {max_int256}
        %7 = iszero %10
        %3 = iszero %7
        assert %3
        %11 = xor %par, {min_int256}
        %8 = iszero %11
        %4 = iszero %8
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
        %par = param
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
        %par = param
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
        %par = param
        %1 = lt {abs_down}, %par
        %3 = gt {abs_up}, %par
        %5 = slt {down}, %par
        %7 = sgt {up}, %par
        sink %1, %3, %5, %7
    """

    _check_pre_post(pre1, post)
    _check_pre_post(pre2, post)
