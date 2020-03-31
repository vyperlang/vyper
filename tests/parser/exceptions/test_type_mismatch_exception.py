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
def test_func() -> int128:
    return (1, 2)
    """,
    """
@public
def foo():
    x: uint256 = as_wei_value(0x05, "babbage")
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_type_mismatch_exception(bad_code):
    with raises(TypeMismatch):
        compiler.compile_code(bad_code)
