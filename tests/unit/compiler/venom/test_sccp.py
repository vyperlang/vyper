import pytest

from tests.venom_utils import PrePostChecker
from vyper.exceptions import StaticAssertionException
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRVariable
from vyper.venom.parser import parse_venom
from vyper.venom.passes import SCCP
from vyper.venom.passes.sccp.sccp import LatticeEnum

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([SCCP])


def test_simple_case():
    """
    Test of basic operation
    """
    pre = """
    _global:
        %1 = source
        %2 = 32
        %3 = 64
        %4 = add %2, %3
        %5 = add %1, 8  ; can't be optimized since %1 is a variable
        sink %4, %5
    """

    post = """
    _global:
        %1 = source
        %2 = 32
        %3 = 64
        %4 = add 32, 64
        %5 = add %1, 8
        sink 96, %5
    """

    passes = _check_pre_post(pre, post)
    sccp: SCCP = passes[0]  # type: ignore

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96


def test_branch_eliminator_simple():
    """
    Test of simplifying the jnz if the condition is known
    at compile time
    """
    pre = """
    main:
        jnz 1, @then, @else
    then:
        jmp @foo
    else:
        sink 1
    foo:
        jnz 0, @foo, @bar
    bar:
        ; test when condition not in (0, 1)
        jnz 100, @else, @foo
    """

    post = """
    main:
        jmp @then
    then:
        jmp @foo
    else:
        sink 1
    foo:
        jmp @bar
    bar:
        jmp @else
    """

    _check_pre_post(pre, post)


def test_assert_elimination():
    """
    Test of compile time evaluation of asserts
    the positive case
    """
    pre = """
    main:
        assert 1
        assert_unreachable 1
        assert 100
        assert_unreachable 100
        sink 1
    """

    post = """
    main:
        nop
        nop
        nop
        nop
        sink 1
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("asserter", ("assert", "assert_unreachable"))
def test_assert_false(asserter):
    """
    Test of compile time evaluation of asserts
    the negative case
    """
    code = f"""
    main:
        {asserter} 0
        stop
    """

    with pytest.raises(StaticAssertionException):
        _check_pre_post(code, code, hevm=False)


def test_cont_jump_case():
    """
    Test of jnz removal which eliminates the basic block
    """
    pre = """
    main:
        %1 = source
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
        %1 = source
        %2 = 32
        %3 = 64
        %4 = add 64, 32
        jmp @then
    then:
        %5 = add 10, 96
        sink 106
    else:  # unreachable
        %6 = add %1, 96
        sink %6
    """

    passes = _check_pre_post(pre, post)
    sccp = passes[0]
    assert isinstance(sccp, SCCP)

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5")].value == 106
    assert sccp.lattice[IRVariable("%6")] == LatticeEnum.TOP  # never visited


def test_cont_phi_case():
    """
    Test of jnz removal with phi correction
    """

    pre = """
    main:
        %1 = source
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
        %1 = source
        %2 = 32
        %3 = 64
        %4 = add 64, 32
        jmp @then
    then:
        %5:1 = add 10, 96
        jmp @join
    else:  # unreachable
        %5:2 = add %1, 96
        jmp @join
    join:
        %5 = phi @then, %5:1, @else, %5:2
        sink 106
    """

    passes = _check_pre_post(pre, post)
    sccp = passes[0]
    assert isinstance(sccp, SCCP)

    assert sccp.lattice[IRVariable("%1")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5:1")].value == 106
    assert sccp.lattice[IRVariable("%5:2")] == LatticeEnum.TOP  # never visited
    assert sccp.lattice[IRVariable("%5")].value == 106


def test_cont_phi_const_case():
    """
    Test of jnz removal with phi correction
    with all of the values known at compile
    time
    """
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
    else:  # unreachable
        %5:2 = add 1, 96
        jmp @join
    join:
        %5 = phi @then, %5:1, @else, %5:2
        sink 106
    """

    passes = _check_pre_post(pre, post)
    sccp = passes[0]
    assert isinstance(sccp, SCCP)

    assert sccp.lattice[IRVariable("%1")].value == 1
    assert sccp.lattice[IRVariable("%2")].value == 32
    assert sccp.lattice[IRVariable("%3")].value == 64
    assert sccp.lattice[IRVariable("%4")].value == 96
    assert sccp.lattice[IRVariable("%5:1")].value == 106
    assert sccp.lattice[IRVariable("%5")].value == 106

    # never visited
    assert sccp.lattice[IRVariable("%5:2")] == LatticeEnum.TOP


def test_sccp_phi_operand_top_no_branch():
    """
    control jumps directly to a join block where a phi depends on predecessors
    that haven't been executed yet. The phi is TOP at first, and hhe arithmetic
    using it must defer evaluation.
    """
    # NOTE: `main` goes straight to `@join`, yet the phi still lists `@then`
    # and `@else` as inputs. This intentionally mimics malformed IR seen in
    # programs where the CFG includes those predecessors even though
    # execution never reaches them (and will be prunned by a later pass).
    # So here we show that can SCCP gracefully treat the phi inputs
    # as TOP until (and unless) those blocks are actually visited. Decoupling
    # essentially the CGF from the SCCP.
    pre = """
    main:
        jmp @join
    then:
        %a_then = 2
        jmp @join
    else:
        %a_else = 3
        jmp @join
    join:
        %phi = phi @then, %a_then, @else, %a_else
        %out = sub 14, %phi
        sink %out
    """

    _check_pre_post(pre, pre, hevm=False)


def test_sccp_jnz_top_phi_text_ir():
    """
    Same as above but using the value to control a jnz.
    This used to assert in SCCP when the jnz condition was TOP.
    """
    # NOTE: `main` goes straight to `@join`, yet the phi still lists `@then`
    # and `@else` as inputs. This intentionally mimics malformed IR seen in
    # programs where the CFG includes those predecessors even though
    # execution never reaches them (and will be prunned by a later pass).
    # So here we show that can SCCP gracefully treat the phi inputs
    # as TOP until (and unless) those blocks are actually visited. Decoupling
    # essentially the CGF from the SCCP.
    src = """
    function main {
    main:
        jmp @join
    then:
        %a_then = 2
        jmp @join
    else:
        %a_else = 3
        jmp @join
    join:
        %phi = phi @then, %a_then, @else, %a_else
        jnz %phi, @true, @false
    true:
        sink 1
    false:
        sink 2
    }
    """

    ctx = parse_venom(src)
    fn = ctx.get_function(next(iter(ctx.functions.keys())))
    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()


def test_phi_reduction_without_basic_block_removal():
    """
    Test of phi reduction `if` end not `if-else`
    """
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
        %3 = phi @main, %1, @then, %2
        sink 2
    """

    _check_pre_post(pre, post)


inst = ["mload", "sload", "dload", "iload", "calldataload", "param"]


@pytest.mark.parametrize("inst", inst)
def test_mload_schedules_uses(inst):
    pre = f"""
    main:
        %cond = param
        jnz %cond, @B, @A
    A:
        %m = {inst} 0
        jmp @join
    B:
        %x = assign %m
        jmp @join
    join:
        sink %x
    """

    passes = _check_pre_post(pre, pre, hevm=False)
    sccp = passes[0]
    assert isinstance(sccp, SCCP)

    assert sccp.lattice[IRVariable("%m")] == LatticeEnum.BOTTOM
    assert sccp.lattice[IRVariable("%x")] == LatticeEnum.BOTTOM
