import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    TypeMismatch,
)

fail_list = [
    """
@public
def foo() -> int128:
    x: int128 = 45
    return x.codesize
    """,
    """
@public
def foo() -> int128(wei):
    x: address = 0x1234567890123456789012345678901234567890
    return x.codesize
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_block_fail(bad_code):

    with raises(TypeMismatch):
        compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo() -> int128:
    x: address = 0x1234567890123456789012345678901234567890
    return x.codesize
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None
