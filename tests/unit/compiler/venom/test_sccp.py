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


def test_assert_negative_truthy():
    """
    Test of compile time evaluation of asserts
    with negative nonzero constants.
    """
    pre = """
    main:
        assert -1
        assert_unreachable -1
        sink 1
    """

    post = """
    main:
        nop
        nop
        sink 1
    """

    _check_pre_post(pre, post, hevm=False)


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


# =============================================================================
# Arithmetic Operation Tests
# =============================================================================


def test_sccp_sub():
    """Test subtraction constant folding"""
    pre = """
    _global:
        %1 = 100
        %2 = 30
        %3 = sub %1, %2
        sink %3
    """
    post = """
    _global:
        %1 = 100
        %2 = 30
        %3 = sub 100, 30
        sink 70
    """
    _check_pre_post(pre, post)


def test_sccp_mul():
    """Test multiplication constant folding"""
    pre = """
    _global:
        %1 = 7
        %2 = 6
        %3 = mul %1, %2
        sink %3
    """
    post = """
    _global:
        %1 = 7
        %2 = 6
        %3 = mul 7, 6
        sink 42
    """
    _check_pre_post(pre, post)


def test_sccp_div():
    """Test division constant folding"""
    pre = """
    _global:
        %1 = 100
        %2 = 10
        %3 = div %1, %2
        sink %3
    """
    post = """
    _global:
        %1 = 100
        %2 = 10
        %3 = div 100, 10
        sink 10
    """
    _check_pre_post(pre, post)


def test_sccp_div_by_zero():
    """Test division by zero returns 0 per EVM semantics"""
    pre = """
    _global:
        %1 = 100
        %2 = 0
        %3 = div %1, %2
        sink %3
    """
    post = """
    _global:
        %1 = 100
        %2 = 0
        %3 = div 100, 0
        sink 0
    """
    _check_pre_post(pre, post)


def test_sccp_mod_by_zero():
    """Test modulo by zero returns 0 per EVM semantics"""
    pre = """
    _global:
        %1 = 100
        %2 = 0
        %3 = mod %1, %2
        sink %3
    """
    post = """
    _global:
        %1 = 100
        %2 = 0
        %3 = mod 100, 0
        sink 0
    """
    _check_pre_post(pre, post)


# =============================================================================
# Comparison Operation Tests
# =============================================================================


def test_sccp_lt():
    """Test less-than comparison"""
    pre = """
    _global:
        %1 = 5
        %2 = 10
        %3 = lt %1, %2
        sink %3
    """
    post = """
    _global:
        %1 = 5
        %2 = 10
        %3 = lt 5, 10
        sink 1
    """
    _check_pre_post(pre, post)


def test_sccp_gt():
    """Test greater-than comparison"""
    pre = """
    _global:
        %1 = 10
        %2 = 5
        %3 = gt %1, %2
        sink %3
    """
    post = """
    _global:
        %1 = 10
        %2 = 5
        %3 = gt 10, 5
        sink 1
    """
    _check_pre_post(pre, post)


def test_sccp_eq():
    """Test equality comparison"""
    pre = """
    _global:
        %1 = 42
        %2 = 42
        %3 = eq %1, %2
        sink %3
    """
    post = """
    _global:
        %1 = 42
        %2 = 42
        %3 = eq 42, 42
        sink 1
    """
    _check_pre_post(pre, post)


def test_sccp_iszero():
    """Test iszero operation"""
    pre = """
    _global:
        %1 = 0
        %2 = iszero %1
        %3 = 42
        %4 = iszero %3
        sink %2, %4
    """
    post = """
    _global:
        %1 = 0
        %2 = iszero 0
        %3 = 42
        %4 = iszero 42
        sink 1, 0
    """
    _check_pre_post(pre, post)


# =============================================================================
# Bitwise Operation Tests
# =============================================================================


def test_sccp_and():
    """Test bitwise AND"""
    pre = """
    _global:
        %1 = 15
        %2 = 7
        %3 = and %1, %2
        sink %3
    """
    post = """
    _global:
        %1 = 15
        %2 = 7
        %3 = and 15, 7
        sink 7
    """
    _check_pre_post(pre, post)


def test_sccp_or():
    """Test bitwise OR"""
    pre = """
    _global:
        %1 = 8
        %2 = 4
        %3 = or %1, %2
        sink %3
    """
    post = """
    _global:
        %1 = 8
        %2 = 4
        %3 = or 8, 4
        sink 12
    """
    _check_pre_post(pre, post)


def test_sccp_xor():
    """Test bitwise XOR"""
    pre = """
    _global:
        %1 = 15
        %2 = 10
        %3 = xor %1, %2
        sink %3
    """
    post = """
    _global:
        %1 = 15
        %2 = 10
        %3 = xor 15, 10
        sink 5
    """
    _check_pre_post(pre, post)


# =============================================================================
# Shift Operation Tests
# =============================================================================


def test_sccp_shl():
    """Test shift left"""
    pre = """
    _global:
        %1 = 1
        %2 = 4
        %3 = shl %2, %1
        sink %3
    """
    post = """
    _global:
        %1 = 1
        %2 = 4
        %3 = shl 4, 1
        sink 16
    """
    _check_pre_post(pre, post)


def test_sccp_shr():
    """Test shift right"""
    pre = """
    _global:
        %1 = 16
        %2 = 2
        %3 = shr %2, %1
        sink %3
    """
    post = """
    _global:
        %1 = 16
        %2 = 2
        %3 = shr 2, 16
        sink 4
    """
    _check_pre_post(pre, post)


def test_sccp_sar():
    """Test arithmetic shift right"""
    pre = """
    _global:
        %1 = 16
        %2 = 2
        %3 = sar %2, %1
        sink %3
    """
    post = """
    _global:
        %1 = 16
        %2 = 2
        %3 = sar 2, 16
        sink 4
    """
    _check_pre_post(pre, post)


def test_sccp_sar_large_shift():
    """
    Test SAR with large shift amount (>= 256).
    Regression test for bug where shift >= 2^255 caused AssertionError.
    """
    from vyper.utils import SizeLimits
    from vyper.venom.basicblock import IRLiteral
    from vyper.venom.passes.sccp.eval import eval_arith

    # Test: sar 300, -1 should return MAX_UINT256 (all ones, -1 signed)
    # because shift >= 256 and value < 0
    ops = [IRLiteral(-1), IRLiteral(300)]
    result = eval_arith("sar", ops)
    assert result == SizeLimits.MAX_UINT256

    # Test: sar 300, 100 should return 0
    # because shift >= 256 and value >= 0
    ops = [IRLiteral(100), IRLiteral(300)]
    result = eval_arith("sar", ops)
    assert result == 0

    # Test: sar 2^255, -1 (large unsigned shift stored as negative)
    # This was the original bug trigger
    large_shift_stored = SizeLimits.MIN_INT256  # -2^255 stored = 2^255 unsigned
    ops = [IRLiteral(-1), IRLiteral(large_shift_stored)]
    result = eval_arith("sar", ops)
    assert result == SizeLimits.MAX_UINT256


# =============================================================================
# Overflow / Boundary Tests
# =============================================================================


def test_sccp_overflow_add():
    """Test that addition wraps at 2^256"""
    from vyper.utils import SizeLimits
    from vyper.venom.basicblock import IRLiteral
    from vyper.venom.passes.sccp.eval import eval_arith

    # MAX_UINT256 + 1 should wrap to 0
    max_stored = SizeLimits.MAX_UINT256 - 2**256  # stored as -1
    ops = [IRLiteral(1), IRLiteral(max_stored)]
    result = eval_arith("add", ops)
    assert result == 0


def test_sccp_underflow_sub():
    """Test that subtraction wraps at 2^256"""
    from vyper.utils import SizeLimits
    from vyper.venom.basicblock import IRLiteral
    from vyper.venom.passes.sccp.eval import eval_arith

    # 0 - 1 should wrap to MAX_UINT256
    ops = [IRLiteral(1), IRLiteral(0)]
    result = eval_arith("sub", ops)
    assert result == SizeLimits.MAX_UINT256


# =============================================================================
# Signed Operation Tests
# =============================================================================


def test_sccp_slt():
    """Test signed less-than comparison"""
    from vyper.venom.basicblock import IRLiteral
    from vyper.venom.passes.sccp.eval import eval_arith

    # -1 < 1 should be true (signed comparison)
    ops = [IRLiteral(1), IRLiteral(-1)]  # is -1 < 1?
    result = eval_arith("slt", ops)
    assert result == 1

    # 1 < -1 should be false
    ops = [IRLiteral(-1), IRLiteral(1)]  # is 1 < -1?
    result = eval_arith("slt", ops)
    assert result == 0


def test_sccp_sgt():
    """Test signed greater-than comparison"""
    from vyper.venom.basicblock import IRLiteral
    from vyper.venom.passes.sccp.eval import eval_arith

    # 1 > -1 should be true (signed comparison)
    ops = [IRLiteral(-1), IRLiteral(1)]  # is 1 > -1?
    result = eval_arith("sgt", ops)
    assert result == 1


# =============================================================================
# Loop with Phi Tests
# =============================================================================


def test_sccp_loop_phi_constant():
    """Test that phi in a loop with constant values works correctly"""
    pre = """
    main:
        %init = 0
        jmp @loop
    loop:
        %i = phi @main, %init, @loop, %next
        %next = add %i, 1
        %cond = lt %i, 10
        jnz %cond, @loop, @exit
    exit:
        sink %i
    """
    # The phi merges constant and non-constant, so result should be BOTTOM
    passes = _check_pre_post(pre, pre, hevm=False)
    sccp = passes[0]
    assert isinstance(sccp, SCCP)
    # %i should be BOTTOM because it depends on loop iteration
    assert sccp.lattice[IRVariable("%i")] == LatticeEnum.BOTTOM


# =============================================================================
# Ternary Operation Tests (addmod, mulmod)
# =============================================================================


def test_sccp_addmod():
    """Test addmod constant folding"""
    pre = """
    _global:
        %a = 10
        %b = 20
        %n = 7
        %r = addmod %a, %b, %n
        sink %r
    """
    post = """
    _global:
        %a = 10
        %b = 20
        %n = 7
        %r = addmod 10, 20, 7
        sink 2
    """
    # (10 + 20) % 7 = 30 % 7 = 2
    _check_pre_post(pre, post)


def test_sccp_addmod_zero_mod():
    """Test addmod with zero modulus returns 0"""
    from vyper.venom.basicblock import IRLiteral
    from vyper.venom.passes.sccp.eval import eval_arith

    # addmod(10, 20, 0) = 0 per EVM semantics
    ops = [IRLiteral(0), IRLiteral(20), IRLiteral(10)]
    result = eval_arith("addmod", ops)
    assert result == 0


def test_sccp_mulmod():
    """Test mulmod constant folding"""
    pre = """
    _global:
        %a = 10
        %b = 20
        %n = 7
        %r = mulmod %a, %b, %n
        sink %r
    """
    post = """
    _global:
        %a = 10
        %b = 20
        %n = 7
        %r = mulmod 10, 20, 7
        sink 4
    """
    # (10 * 20) % 7 = 200 % 7 = 4
    _check_pre_post(pre, post)


def test_sccp_mulmod_zero_mod():
    """Test mulmod with zero modulus returns 0"""
    from vyper.venom.basicblock import IRLiteral
    from vyper.venom.passes.sccp.eval import eval_arith

    # mulmod(10, 20, 0) = 0 per EVM semantics
    ops = [IRLiteral(0), IRLiteral(20), IRLiteral(10)]
    result = eval_arith("mulmod", ops)
    assert result == 0


# =============================================================================
# Byte Operation Tests
# =============================================================================


def test_sccp_byte():
    """Test byte constant folding"""
    pre = """
    _global:
        %val = 0x1234567890
        %idx = 31
        %b = byte %idx, %val
        sink %b
    """
    post = """
    _global:
        %val = 0x1234567890
        %idx = 31
        %b = byte 31, 0x1234567890
        sink 144
    """
    # byte(31, 0x1234567890) extracts LSB = 0x90 = 144
    _check_pre_post(pre, post, hevm=False)


def test_sccp_byte_msb():
    """Test byte extraction of MSB"""
    pre = """
    _global:
        %val = 0x42000000000000000000000000000000000000000000000000000000000000
        %idx = 0
        %b = byte %idx, %val
        sink %b
    """
    post = """
    _global:
        %val = 0x42000000000000000000000000000000000000000000000000000000000000
        %idx = 0
        %b = byte 0, 0x42000000000000000000000000000000000000000000000000000000000000
        sink 0
    """
    # 0x42 is not at the MSB position (byte 0) for this value
    _check_pre_post(pre, post, hevm=False)


def test_sccp_byte_out_of_range():
    """Test byte with index >= 32 returns 0"""
    pre = """
    _global:
        %val = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
        %idx = 32
        %b = byte %idx, %val
        sink %b
    """
    post = """
    _global:
        %val = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
        %idx = 32
        %b = byte 32, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
        sink 0
    """
    _check_pre_post(pre, post, hevm=False)


def test_sccp_byte_all_ones():
    """Test byte extraction from max uint256 (all 0xFF bytes)"""
    from vyper.utils import SizeLimits
    from vyper.venom.basicblock import IRLiteral
    from vyper.venom.passes.sccp.eval import eval_arith

    # byte(31, 2^256-1) should return 0xFF
    max_uint = SizeLimits.MAX_UINT256
    ops = [IRLiteral(max_uint), IRLiteral(31)]
    result = eval_arith("byte", ops)
    assert result == 0xFF

    # byte(0, 2^256-1) should also return 0xFF (MSB)
    ops = [IRLiteral(max_uint), IRLiteral(0)]
    result = eval_arith("byte", ops)
    assert result == 0xFF
