import pytest

from vyper import compiler
from vyper.exceptions import InvalidType, SyntaxException, TypeMismatch

fail_list = [
    (
        """
@public
def foo():
    x: bytes[9] = raw_call(
        0x1234567890123456789012345678901234567890, b"cow", max_outsize=4, max_outsize=9
    )
    """,
        SyntaxException,
    ),
    (
        """
@public
def foo():
    raw_log([b"cow"], b"dog")
    """,
        InvalidType,
    ),
    """
@public
def foo():
    raw_log([], 0x1234567890123456789012345678901234567890)
    """,
    (
        """
@public
def foo():
    # fails because raw_call without max_outsize does not return a value
    x: bytes[9] = raw_call(0x1234567890123456789012345678901234567890, b"cow")
    """,
        InvalidType,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_raw_call_fail(bad_code):

    if isinstance(bad_code, tuple):
        with pytest.raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with pytest.raises(TypeMismatch):
            compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo():
    x: bytes[9] = raw_call(
        0x1234567890123456789012345678901234567890,
        b"cow",
        max_outsize=4,
        gas=595757
    )
    """,
    """
@public
def foo():
    x: bytes[9] = raw_call(
        0x1234567890123456789012345678901234567890,
        b"cow",
        max_outsize=4,
        gas=595757,
        value=as_wei_value(9, "wei")
    )
    """,
    """
@public
def foo():
    x: bytes[9] = raw_call(
        0x1234567890123456789012345678901234567890,
        b"cow",
        max_outsize=4,
        gas=595757,
        value=9
    )
    """,
    """
@public
def foo():
    raw_call(0x1234567890123456789012345678901234567890, b"cow")
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_raw_call_success(good_code):
    assert compiler.compile_code(good_code) is not None
