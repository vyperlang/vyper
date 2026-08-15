import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import ArgumentException, SyntaxException

fail_list = [
    """
@external
def foo():
    x: address = create_minimal_proxy_to(
        0x1234567890123456789012345678901234567890,
        value=4,
        value=9
    )
    """,
    """
@external
def foo(_salt: bytes32):
    x: address = create_minimal_proxy_to(
        0x1234567890123456789012345678901234567890, salt=keccak256(b"Vyper Rocks!"), salt=_salt
    )
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_type_mismatch_exception(bad_code):
    with raises((SyntaxException, ArgumentException)):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo():
    # test that create_forwarder_to is valid syntax; the name is deprecated
    x: address = create_forwarder_to(0x1234567890123456789012345678901234567890)
    """,
    """
@external
def foo():
    x: address = create_minimal_proxy_to(0x1234567890123456789012345678901234567890)
    """,
    """
@external
def foo():
    x: address = create_minimal_proxy_to(
        0x1234567890123456789012345678901234567890,
        value=as_wei_value(9, "wei")
    )
    """,
    """
@external
def foo():
    x: address = create_minimal_proxy_to(0x1234567890123456789012345678901234567890, value=9)
    """,
    """
@external
def foo():
    x: address = create_minimal_proxy_to(
        0x1234567890123456789012345678901234567890,
        salt=keccak256(b"Vyper Rocks!")
    )
    """,
    """
@external
def foo(_salt: bytes32):
    x: address = create_minimal_proxy_to(0x1234567890123456789012345678901234567890, salt=_salt)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_rlp_success(good_code):
    assert compiler.compile_code(good_code) is not None
