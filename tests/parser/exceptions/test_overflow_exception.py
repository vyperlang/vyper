import pytest

from vyper import (
    compiler,
)
from vyper.exceptions import (
    OverflowException,
)

fail_list = [
    """
@public
def foo():
    x: int128 = -170141183460469231731687303715884105729 # -2**127 - 1
    """,
    """
@public
def foo():
    x: decimal = -170141183460469231731687303715884105728.1
    """,
    """
@public
def overflow2() -> uint256:
    a: uint256 = 2**256
    return a
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_literal_exception(bad_code):
    with pytest.raises(OverflowException):
        compiler.compile_code(bad_code)
