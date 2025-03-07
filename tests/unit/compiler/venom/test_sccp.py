import pytest

from tests.venom_utils import PrePostChecker
from vyper.exceptions import StaticAssertionException
from vyper.venom.basicblock import IRVariable
from vyper.venom.passes import SCCP, SimplifyCFGPass
from vyper.venom.passes.sccp.sccp import LatticeEnum

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker(SCCP)


def test_simple_case():
    pre = """
    _global:
        %1 = param
        %2 = 32
        %3 = 64
        %4 = add %2, %3
        sink %1, %4
    """

    post = """
    _global:
        %1 = param
        %2 = 32
        %3 = 64
        %4 = add 32, 64
        sink %1, 96
    """

    passes = _check_pre_post(pre, post)
    sccp: SCCP = passes[0]  # type: ignore

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96


def test_branch_eliminator_simple():
    pre = """
    main:
        jnz 1, @then, @else
    then:
        jmp @foo
    else:
        sink 1
    foo:
        jnz 0, @then, @else
    """

    post = """
    main:
        jmp @then
    then:
        jmp @foo
    else:
        sink 1
    foo:
        jmp @else
    """

    _check_pre_post(pre, post, hevm=True)


def test_assert_elimination():
    pre = """
    main:
        assert 1
        assert_unreachable 1
        sink 1
    """

    post = """
    main:
        nop
        nop
        sink 1
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("asserter", ("assert", "assert_unreachable"))
def test_assert_false(asserter):
    code = f"""
    main:
        {asserter} 0
        stop
    """

    with pytest.raises(StaticAssertionException):
        _check_pre_post(code, code, hevm=False)


def test_cont_jump_case():
    pre = """
    main:
        %1 = param
        %2 = 32
        %3 = 64
        %4 = add %3, %2
        jnz %4, @then, @else
    then:
        %5 = add 10, %4
        sink %5
    else:
        %6 = add %1, %4
        sink %6
    """

    post = """
    main:
        %1 = param
        %2 = 32
        %3 = 64
        %4 = add 64, 32
        jmp @then
    then:
        %5 = add 10, 96
        sink 106
    """

    passes = _check_pre_post(pre, post)
    sccp = passes[0]
    assert isinstance(sccp, SCCP)

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5")].value == 106
    assert sccp.lattice.get(IRVariable("%6")) == LatticeEnum.BOTTOM


def test_cont_phi_case():
    pre = """
    main:
        %1 = param
        %2 = 32
        %3 = 64
        %4 = add %3, %2
        jnz %4, @then, @else
    then:
        %5:1 = add 10, %4
        jmp @join
    else:
        %5:2 = add %1, %4
        jmp @join
    join:
        %5 = phi @then, %5:1, @else, %5:2
        sink %5
    """

    post = """
    main:
        %1 = param
        %2 = 32
        %3 = 64
        %4 = add 64, 32
        jmp @then
    then:
        %5:1 = add 10, 96
        jmp @join
    join:
        %5 = %5:1
        sink %5
    """

    passes = _check_pre_post(pre, post)
    sccp = passes[0]
    assert isinstance(sccp, SCCP)

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5", version=1)].value == 106
    assert sccp.lattice[IRVariable("%5", version=2)] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%5")].value == 2


def test_cont_phi_const_case():
    pre = """
    main:
        %1 = 1
        %2 = 32
        %3 = 64
        %4 = add %3, %2
        jnz %4, @then, @else
    then:
        %5:1 = add 10, %4
        jmp @join
    else:
        %5:2 = add %1, %4
        jmp @join
    join:
        %5 = phi @then, %5:1, @else, %5:2
        sink %5
    """

    post = """
    main:
        %1 = 1
        %2 = 32
        %3 = 64
        %4 = add 64, 32
        jmp @then
    then:
        %5:1 = add 10, 96
        jmp @join
    join:
        %5 = %5:1
        sink %5
    """

    passes = _check_pre_post(pre, post)
    sccp = passes[0]
    assert isinstance(sccp, SCCP)

    assert sccp.lattice[IRVariable("%1")].value == 1
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    # dependent on cfg traversal order
    assert sccp.lattice[IRVariable("%5", version=1)].value == 106
    assert sccp.lattice[IRVariable("%5", version=2)].value == 97
    assert sccp.lattice[IRVariable("%5")].value == 2


def test_phi_reduction_after_unreachable_block():
    pre = """
    main:
        %1 = 1
        jnz 1, @then, @join
    then:
        %2 = 2
        jmp @join
    join:
        %3 = phi @main, %1, @then, %2
        sink %3
    """

    post = """
    main:
        %1 = 1
        jmp @then
    then:
        %2 = 2
        jmp @join
    join:
        %3 = %2
        sink 2
    """

    _check_pre_post(pre, post)
