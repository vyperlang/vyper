import pytest

from vyper import compiler
from vyper.exceptions import TypeMismatch, UndeclaredDefinition

type_fail_list = [
    """
@external
def foo():
    x: bytes32 = keccak256(3)
    """
]


@pytest.mark.parametrize("bad_code", type_fail_list)
def test_block_type_fail(bad_code):
    with pytest.raises(TypeMismatch):
        compiler.compile_code(bad_code)


structure_fail_list = [
    """
@external
def foo():
    x: bytes32 = sha3("moose")
    """,
    """
@external
def foo():
    x: bytes32 = sha3(0x1234567890123456789012345678901234567890123456789012345678901234)
    """,
]


@pytest.mark.parametrize("bad_code", structure_fail_list)
def test_block_structure_fail(bad_code):
    with pytest.raises(UndeclaredDefinition):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo():
    x: bytes32 = keccak256("moose")
    """,
    """
@external
def foo():
    x: bytes32 = keccak256(0x1234567890123456789012345678901234567890123456789012345678901234)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None
