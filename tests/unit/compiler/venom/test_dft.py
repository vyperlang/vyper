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


@pytest.mark.parametrize("call_op", ["call", "staticcall", "delegatecall"])
def test_dft_does_not_reorder_gas_across_calls(call_op):
    """
    `gas` must stay on the same side of a call: the call consumes gas,
    so moving a `gas` read across it changes the value read.
    """
    value = "5, " if call_op == "call" else ""
    pre = f"""
    main:
        %a = gas
        %ok = {call_op} 100000, 0x12, {value}1, 2, 3, 4
        %b = gas
        %d = sub %a, %b
        sink %d, %ok
    """
    _check_no_change(pre)


def test_dft_does_not_reorder_gas_reads():
    """
    two `gas` reads must keep their order: the later read sees less gas.
    """
    pre = """
    main:
        %a = gas
        %b = gas
        sink %a, %b
    """
    _check_no_change(pre)
