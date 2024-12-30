import pytest

from vyper import compile_code
from vyper.exceptions import TypeMismatch

fail_list = [
    (
        """
@external
def foo():
    y: int256 = abs(
        -57896044618658097711785492504343953926634992332820282019728792003956564819968
    )
    """,
        TypeMismatch,
    )
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_abs_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


valid_list = [
    """
FOO: constant(int256) = -3
BAR: constant(int256) = abs(FOO)

@external
def foo():
    a: int256 = BAR
    """
]


@pytest.mark.parametrize("code", valid_list)
def test_abs_pass(code):
    assert compile_code(code) is not None
