import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.basicblock import IRVariable
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
