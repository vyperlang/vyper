import pytest

from tests.venom_utils import PrePostChecker, parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel, IRVariable
from vyper.venom.passes.rvp import Interval, RangeValuePropagationPass, _inf

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([RangeValuePropagationPass])


def test_simple_range_propagation():
    pre = """
    _global:
        %1 = param
        %2 = 32
        %3 = 64
        %4 = add %2, %3
        %5 = sub %4, %2
        %6 = add %1, %5  ; can't be optimized since %1 is a variable
        exit
    """

    post = """
    _global:
        %1 = param
        %2 = 32
        %3 = 64
        %4 = add 32, 64
        %5 = sub 96, 32
        %6 = add %1, 64
        exit
    """

    passes = _check_pre_post(pre, post)
    rvp = passes[0]

    assert rvp.lattice[IRVariable("%1")] == Interval(-_inf, _inf)
    assert rvp.lattice[IRVariable("%2")] == Interval(32, 32)
    assert rvp.lattice[IRVariable("%3")] == Interval(64, 64)
    assert rvp.lattice[IRVariable("%4")] == Interval(96, 96)
    assert rvp.lattice[IRVariable("%5")] == Interval(64, 64)
    assert rvp.lattice[IRVariable("%6")] == Interval(-_inf, _inf)


def test_branch_elimination_with_ranges():
    pre = """
    main:
        %1 = 10
        %2 = 20
        %3 = add %1, %2
        jnz %3, @then, @else
    then:
        exit
    else:
        exit
    """

    post = """
    main:
        %1 = 10
        %2 = 20
        %3 = add 10, 20
        jmp @then
    then:
        exit
    else:  # unreachable
        exit
    """

    passes = _check_pre_post(pre, post)
    rvp = passes[0]

    assert rvp.lattice[IRVariable("%1")] == Interval(10, 10)
    assert rvp.lattice[IRVariable("%2")] == Interval(20, 20)
    assert rvp.lattice[IRVariable("%3")] == Interval(30, 30)


def test_branch_range_propagation():
    pre = """
    main:
        %1 = param
        %2 = 0
        jnz %1, @then, @else
    then:
        %3 = add %1, %2  ; %1 is non-zero here
        exit
    else:
        %4 = add %1, %2  ; %1 is zero here
        exit
    """

    post = """
    main:
        %1 = param
        %2 = 0
        jnz %1, @then, @else
    then:
        %3 = add %1, 0  ; %1 is non-zero here
        exit
    else:
        %4 = add 0, 0  ; %1 is zero here
        exit
    """

    passes = _check_pre_post(pre, post)
    rvp = passes[0]

    assert rvp.lattice[IRVariable("%1")] == Interval(-_inf, _inf)
    assert rvp.lattice[IRVariable("%2")] == Interval(0, 0)

    then_ctx = rvp._get_context("then")
    assert then_ctx.lattice[IRVariable("%1")] == Interval(-_inf, -1, 1, _inf)
    assert then_ctx.lattice[IRVariable("%2")] == Interval(0, 0)
    assert then_ctx.lattice[IRVariable("%3")] == Interval(-_inf, -1, 1, _inf)

    else_ctx = rvp._get_context("else")
    assert else_ctx.lattice[IRVariable("%1")] == Interval(0, 0)
    assert else_ctx.lattice[IRVariable("%2")] == Interval(0, 0)
    assert else_ctx.lattice[IRVariable("%4")] == Interval(0, 0)


def test_phi_meet_does_not_underapproximate():
    pre = """
    main:
        %cond = param
        jnz %cond, @then, @else
    then:
        %a = add 0, 0
        jmp @join
    else:
        %b = param
        jmp @join
    join:
        %x = phi @then, %a, @else, %b
        jnz %x, @T, @F
    T:
        exit
    F:
        exit
    """

    post = pre

    passes = _check_pre_post(pre, post)
    rvp = passes[0]

    assert rvp.lattice[IRVariable("%x")] == Interval(-_inf, _inf)


def test_disjoint_add_uses_non_disjoint_max():
    ctx = parse_from_basic_block("main:\n    exit\n", funcname="_global")
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    rvp = RangeValuePropagationPass(ac, fn)

    disjoint = Interval(-_inf, -1, 1, _inf)
    non_disjoint = Interval(10, 11)
    assert rvp._apply_arithmetic(disjoint, non_disjoint, "add") == Interval(-_inf, 10, 11, _inf)


def test_contiguous_minus_disjoint_respects_operand_order():
    ctx = parse_from_basic_block("main:\n    exit\n", funcname="_global")
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    rvp = RangeValuePropagationPass(ac, fn)

    a = Interval(10, 10)
    b = Interval(-_inf, -1, 1, _inf)
    assert rvp._apply_arithmetic(a, b, "sub") == Interval(-_inf, 9, 11, _inf)


def test_disjoint_add_merges_overlapping_segments():
    ctx = parse_from_basic_block("main:\n    exit\n", funcname="_global")
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    rvp = RangeValuePropagationPass(ac, fn)

    disjoint = Interval(-_inf, -1, 1, _inf)
    non_disjoint = Interval(10, 20)
    assert rvp._apply_arithmetic(disjoint, non_disjoint, "add") == Interval(-_inf, _inf)
