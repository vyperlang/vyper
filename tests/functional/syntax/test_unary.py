import pytest

from vyper import compile_code
from vyper.exceptions import TypeMismatch

fail_list = [
    (
        """
@external
def foo() -> int128:
    return -2**127
    """,
        TypeMismatch,
    )
]


@pytest.mark.parametrize("code,exc", fail_list)
def test_unary_fail(code, exc):
    with pytest.raises(exc):
        compile_code(code)
