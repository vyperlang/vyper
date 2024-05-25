import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import NonPayableViolation

fail_list = [
    """
@external
def foo():
    x: uint256 = msg.value
"""
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_variable_declaration_exception(bad_code):
    with raises(NonPayableViolation):
        compiler.compile_code(bad_code)


valid_list = [
    """
x: int128
@external
@payable
def foo() -> int128:
    self.x = 5
    return self.x
    """,
    """
@external
@payable
def foo():
    x: uint256 = msg.value
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None
