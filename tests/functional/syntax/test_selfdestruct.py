import pytest

from vyper import compiler
from vyper.exceptions import TypeMismatch

fail_list = [
    """
@external
def foo():
    selfdestruct(7)
    """
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_block_fail(bad_code):
    with pytest.raises(TypeMismatch):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo():
    selfdestruct(0x1234567890123456789012345678901234567890)
    """
]


@pytest.mark.parametrize("good_code", valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None
