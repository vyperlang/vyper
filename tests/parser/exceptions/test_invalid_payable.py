import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    NonPayableViolation,
)

fail_list = [
    """
@public
def foo():
    x = msg.value
"""
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_variable_decleration_exception(bad_code):
    with raises(NonPayableViolation):
        compiler.compile_code(bad_code)


valid_list = [
    """
x: int128
@public
@payable
def foo() -> int128:
    self.x = 5
    return self.x
    """,
    """
@public
@payable
def foo():
    x: wei_value = msg.value
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None
