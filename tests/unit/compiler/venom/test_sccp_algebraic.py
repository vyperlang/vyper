from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import (
    SCCP,
    AlgebraicOptimizationPass,
    RemoveUnusedVariablesPass,
    StoreElimination,
)


def _sccp_algebraic_runner(pre, post):
    ctx = parse_from_basic_block(pre)

    print(ctx)

    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        StoreElimination(ac, fn).run_pass()
        SCCP(ac, fn).run_pass()
        AlgebraicOptimizationPass(ac, fn).run_pass()
        SCCP(ac, fn).run_pass()
        StoreElimination(ac, fn).run_pass()
        RemoveUnusedVariablesPass(ac, fn).run_pass()

    print(ctx)

    assert_ctx_eq(ctx, parse_from_basic_block(post))


def test_sccp_algebraic_opt_sub_xor():
    # x - x -> 0
    # x ^ x -> 0
    pre = """
    _global:
        %par = param
        %1 = sub %par, %par
        %2 = xor %par, %par
        return %1, %2
    """
    post = """
    _global:
        %par = param
        return 0, 0
    """

    _sccp_algebraic_runner(pre, post)


def test_sccp_algebraic_opt_zero_sub_xor():
    # x + 0 == x - 0 == x ^ 0 -> x
    # this cannot be done for 0 - x
    pre = """
    _global:
        %par = param
        %1 = sub %par, 0
        %2 = xor %par, 0
        %3 = add 0, %par
        %4 = sub 0, %par
        return %1, %2, %3, %4
    """
    post = """
    _global:
        %par = param
        %4 = sub 0, %par
        return %par, %par, %par, %4
    """

    _sccp_algebraic_runner(pre, post)


def test_sccp_algebraic_opt_xor_max():
    # x ^ 0xFF..FF -> not x
    pre = """
    _global:
        %par = param
        %tmp = 115792089237316195423570985008687907853269984665640564039457584007913129639935
        %1 = xor %tmp, %par
        return %1
    """
    post = """
    _global:
        %par = param
        %1 = not %par
        return %1
    """

    _sccp_algebraic_runner(pre, post)


def test_sccp_algebraic_opt_shift():
    # x << 0 == x >> 0 == x (sar) 0 -> x
    # sar is right arithmetic shift
    pre = """
    _global:
        %par = param
        %1 = shl 0, %par
        %2 = shr 0, %1
        %3 = sar 0, %2
        return %1, %2, %3
    """
    post = """
    _global:
        %par = param
        return %par, %par, %par
    """

    _sccp_algebraic_runner(pre, post)


def test_sccp_algebraic_opt_div_mul_and():
    # x * 0 == 0 * x == x / 0 == x % 0 == x & 0 == 0 & x -> 0
    # checks for non comutative ops
    pre = """
    _global:
        %par = param
        %1_1 = mul 0, %par
        %1_2 = mul %par, 0
        %2_1 = div 0, %par
        %2_2 = div %par, 0
        %3_1 = sdiv 0, %par
        %3_2 = sdiv %par, 0
        %4_1 = mod 0, %par
        %4_2 = mod %par, 0
        %5_1 = smod 0, %par
        %5_2 = smod %par, 0
        %6_1 = and 0, %par
        %6_2 = and %par, 0
        return %1_1, %1_2, %2_1, %2_2, %3_1, %3_2, %4_1, %4_2, %5_1, %5_2, %6_1, %6_2
    """
    post = """
    _global:
        %par = param
        %2_1 = div 0, %par
        %3_1 = sdiv 0, %par
        %4_1 = mod 0, %par
        %5_1 = smod 0, %par
        return 0, 0, %2_1, 0, %3_1, 0, %4_1, 0, %5_1, 0, 0, 0
    """

    _sccp_algebraic_runner(pre, post)


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
        return %1_1, %1_2, %2_1, %2_2, %3_1, %3_2
    """
    post = """
    _global:
        %par = param
        %2_1 = div 1, %par
        %3_1 = sdiv 1, %par
        return %par, %par, %2_1, %par, %3_1, %par
    """

    _sccp_algebraic_runner(pre, post)


def test_sccp_algebraic_opt_mod_zero():
    # x % 1 -> 0
    pre = """
    _global:
        %par = param
        %1 = mod %par, 1
        %2 = smod %par, 1
        return %1, %2
    """
    post = """
    _global:
        %par = param
        return 0, 0
    """

    _sccp_algebraic_runner(pre, post)


def test_sccp_algebraic_opt_and_max():
    # x & 0xFF..FF == 0xFF..FF & x -> x
    pre = """
    _global:
        %par = param
        %tmp = 115792089237316195423570985008687907853269984665640564039457584007913129639935
        %1 = and %par, %tmp
        %2 = and %tmp, %par
        return %1, %2
    """
    post = """
    _global:
        %par = param
        return %par, %par
    """

    _sccp_algebraic_runner(pre, post)


def test_sccp_algebraic_opt_mul_div_to_shifts():
    # x * 2**n -> x << n
    # x / 2**n -> x >> n
    pre = """
    _global:
        %par = param
        %1 = mod %par, 8
        %2 = mul %par, 16
        %3 = div %par, 4
        return %1, %2, %3
    """
    post = """
    _global:
        %par = param
        %1 = and %par, 7
        %2 = shl 4, %par
        %3 = shr 2, %par
        return %1, %2, %3
    """

    _sccp_algebraic_runner(pre, post)


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
        return %1, %2, %3, %4
    """
    post = """
    _global:
        %par = param
        %3 = iszero %par
        return 1, 1, %3, %par
    """

    _sccp_algebraic_runner(pre, post)


def test_sccp_algebraic_opt_comperation():
    # x < x == x > x -> 0
    pre = """
    _global:
        %par = param
        %tmp = %par
        %1 = gt %tmp, %par
        %2 = sgt %tmp, %par
        %3 = lt %tmp, %par
        %4 = slt %tmp, %par
        return %1, %2, %3, %4
    """
    post = """
    _global:
        %par = param
        return 0, 0, 0, 0
    """

    _sccp_algebraic_runner(pre, post)


def test_sccp_algebraic_opt_or_eq():
    # x | 0 -> x
    # x | 0xFF..FF -> 0xFF..FF
    # x = 0 == 0 = x -> iszero x
    # x = x -> 1
    pre = """
    _global:
        %par = param
        %1 = or %par, 0
        %tmp = 115792089237316195423570985008687907853269984665640564039457584007913129639935
        %2 = or %par, %tmp
        %3 = eq %par, 0
        %4 = eq 0, %par
        %tmp_par = %par
        %5 = eq %tmp_par, %par
        return %1, %2, %3, %4, %5
    """
    post = """
    _global:
        %par = param
        %3 = iszero %par
        %4 = iszero %par
        return %par, 115792089237316195423570985008687907853269984665640564039457584007913129639935,
               %3, %4, 1
    """

    _sccp_algebraic_runner(pre, post)


def test_sccp_algebraic_opt_boolean_or_eq():
    # x == 1 -> iszero (x xor 1) if it is only used as boolean
    # x | (non zero) -> 1 if it is only used as boolean
    pre = """
    _global:
        %par = param
        %1 = eq %par, 1
        %2 = eq %par, 1
        assert %1
        %3 = or %par, 123
        %4 = or %par, 123
        assert %3
        return %2, %4
    """
    post = """
    _global:
        %par = param
        %5 = xor %par, 1
        %1 = iszero %5
        %2 = eq %par, 1
        assert %1
        %4 = or %par, 123
        nop
        return %2, %4
    """

    _sccp_algebraic_runner(pre, post)


def test_sccp_algebraic_opt_comparison_bounderies():
    # unsigned x > 0xFF..FF == x < 0 -> 0
    # signed: x > MAX_SIGNED (0x3F..FF) == x < MIN_SIGNED (0xF0..00) -> 0
    pre = """
    _global:
        %par = param
        %tmp1 = -57896044618658097711785492504343953926634992332820282019728792003956564819968
        %1 = slt %par, %tmp1
        %tmp2 = 57896044618658097711785492504343953926634992332820282019728792003956564819967
        %2 = sgt %par, %tmp2
        %3 = lt %par, 0
        %tmp3 = 115792089237316195423570985008687907853269984665640564039457584007913129639935
        %4 = gt %par, %tmp3
        return %1, %2, %3, %4
    """
    post = """
    _global:
        %par = param
        return 0, 0, 0, 0
    """

    _sccp_algebraic_runner(pre, post)
