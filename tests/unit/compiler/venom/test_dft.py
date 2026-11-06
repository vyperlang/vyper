import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import DFTPass

_check_pre_post = PrePostChecker([DFTPass])


def _check_no_change(pre):
    _check_pre_post(pre, pre)


def test_dft():
    """
    Basic test for dft pass
    """
    pre = """
    main:
        %x = 1
        %y = 2
        return %x, %y
    """
    post = """
    main:
        %y = 2
        %x = 1
        return %x, %y
    """
    _check_pre_post(pre, post)


def test_dft_does_not_reorder_fmp_register_ops():
    """
    `setfmp` (an FMP register write) must not be reordered across `getfmp`
    reads (and vice versa); the FMP effect row creates the ordering edges.
    """
    pre = """
    main:
        %a = getfmp
        setfmp 128
        %b = getfmp
        sink %a, %b
    """
    _check_no_change(pre)


def test_dft_does_not_hoist_assert_above_invoke():
    """
    An `assert` must not move above an earlier `invoke`: if both fail,
    the callee's revert (with its revert data) must win.
    """
    pre = """
    main:
        invoke @f
        %x = calldataload 0
        %y = add %x, 1
        %c = gt %x, %y
        %ok = iszero %c
        assert %ok
        mstore 0, %y
        return 0, 32
    """
    _check_no_change(pre)


def test_dft_does_not_hoist_assert_above_returndatacopy():
    """
    `returndatacopy` aborts with an exceptional halt and `assert` with a
    revert, so an `assert` must not move above an earlier `returndatacopy`.
    """
    pre = """
    main:
        returndatacopy 64, 0, 32
        %x = calldataload 0
        %ok = iszero %x
        assert %ok
        %y = mload 64
        mstore 32, %y
        return 32, 32
    """
    _check_no_change(pre)


def test_dft_computes_assert_condition_after_earlier_invoke():
    """
    Each `assert` stays after the `invoke` before it, and its condition is
    computed next to it rather than up front, where it would stay on the
    stack across every call.
    """
    pre = """
    main:
        invoke @f
        %x = calldataload 0
        %c1 = iszero %x
        assert %c1
        invoke @f
        %c2 = iszero %x
        assert %c2
        mstore 0, %x
        return 0, 32
    """
    _check_no_change(pre)


def test_dft_long_chain_of_aborts():
    # each `assert` is ordered after the `invoke` before it, so the chain of
    # dependencies is as long as the block
    n = 2000
    body = "".join(
        f"%c{i} = iszero %x\n        assert %c{i}\n        invoke @f\n        " for i in range(n)
    )
    pre = f"""
    main:
        invoke @f
        %x = calldataload 0
        {body}return 0, 32
    """
    _check_no_change(pre)


@pytest.mark.parametrize("create", ["create %val, %off, %sz", "create2 %val, %off, %sz, 0"])
def test_dft_does_not_hoist_mload_above_create(create):
    """
    An `mload` must not move above an earlier `create`/`create2`: a read
    that expands memory would then be paid for before the create, which
    forwards all but 1/64 of the remaining gas to the initcode.
    """
    pre = f"""
    main:
        %sz = calldataload 64
        %off = calldataload 32
        %val = calldataload 0
        %v = {create}
        %y = mload 100000
        sink %v, %y
    """
    _check_no_change(pre)
