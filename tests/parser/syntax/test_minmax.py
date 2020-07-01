import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatch

fail_list = [
    """
@external
def foo():
    y: int128 = min(7, 0x1234567890123456789012345678901234567890)
    """
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_block_fail(bad_code):

    with raises(TypeMismatch):
        compiler.compile_code(bad_code)
