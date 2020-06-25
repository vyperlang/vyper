import pytest

from vyper import compiler
from vyper.exceptions import InvalidReference

fail_list = [
    """
x: uint256

@public
def foo():
    send(0x1234567890123456789012345678901234567890, x)
    """,
    """
@public
def bar(x: int128) -> int128:
    return 3 * x

@public
def foo() -> int128:
    return bar(20)
    """,
    """
b: int128
@public
def foo():
    b = 7
    """,
    """
x: int128
@public
def foo():
    x = 5
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_invalid_reference_exception(bad_code):
    with pytest.raises(InvalidReference):
        compiler.compile_code(bad_code)
