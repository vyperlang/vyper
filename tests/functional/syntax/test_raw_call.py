import pytest

from vyper import compile_code
from vyper.exceptions import ArgumentException, InvalidType, SyntaxException, TypeMismatch

fail_list = [
    (
        """
@external
def foo():
    x: Bytes[9] = raw_call(
        0x1234567890123456789012345678901234567890, b"cow", max_outsize=4, max_outsize=9
    )
    """,
        (SyntaxException, ArgumentException),
    ),
    (
        """
@external
@view
def foo(_addr: bytes4):
    # bytes4 instead of address
    raw_call(_addr, method_id("foo()"))
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo():
    # fails because raw_call without max_outsize does not return a value
    x: Bytes[9] = raw_call(0x1234567890123456789012345678901234567890, b"cow")
    """,
        InvalidType,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_raw_call_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


valid_list = [
    """
@external
def foo():
    x: Bytes[9] = raw_call(
        0x1234567890123456789012345678901234567890,
        b"cow",
        max_outsize=4,
        gas=595757
    )
    """,
    """
@external
def foo():
    x: Bytes[9] = raw_call(
        0x1234567890123456789012345678901234567890,
        b"cow",
        max_outsize=4,
        gas=595757,
        value=as_wei_value(9, "wei")
    )
    """,
    """
@external
def foo():
    x: Bytes[9] = raw_call(
        0x1234567890123456789012345678901234567890,
        b"cow",
        max_outsize=4,
        gas=595757,
        value=9
    )
    """,
    """
@external
def foo():
    raw_call(0x1234567890123456789012345678901234567890, b"cow")
    """,
    """
balances: HashMap[uint256,uint256]
@external
def foo():
    raw_call(
        0x1234567890123456789012345678901234567890,
        b"cow",
        value=self.balance - self.balances[0]
    )
    """,
    # test constants
    """
OUTSIZE: constant(uint256) = 4
REVERT_ON_FAILURE: constant(bool) = True
@external
def foo():
    x: Bytes[9] = raw_call(
        0x1234567890123456789012345678901234567890,
        b"cow",
        max_outsize=OUTSIZE,
        gas=595757,
        revert_on_failure=REVERT_ON_FAILURE
    )
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_raw_call_success(good_code):
    assert compile_code(good_code) is not None
