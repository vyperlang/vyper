import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    SyntaxException,
    TypeMismatch,
)

fail_list = [
    ("""
@public
def foo():
    x: bytes[9] = raw_call(0x1234567890123456789012345678901234567890, b"cow", outsize=4, outsize=9)
    """, SyntaxException),
    """
@public
def foo():
    raw_log([b"cow"], b"dog")
    """,
    """
@public
def foo():
    raw_log([], 0x1234567890123456789012345678901234567890)
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_raw_call_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatch):
            compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo():
    x: bytes[9] = raw_call(
        0x1234567890123456789012345678901234567890,
        b"cow",
        outsize=4,
        gas=595757
    )
    """,
    """
@public
def foo():
    x: bytes[9] = raw_call(
        0x1234567890123456789012345678901234567890,
        b"cow",
        outsize=4,
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
        outsize=4,
        gas=595757,
        value=9
    )
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_raw_call_success(good_code):
    assert compiler.compile_code(good_code) is not None
