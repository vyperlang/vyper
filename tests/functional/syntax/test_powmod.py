import pytest

from vyper import compile_code
from vyper.exceptions import TypeMismatch

fail_list = [
    (
        """
@external
def foo():
    a: uint256 = pow_mod256(-1, -1)
    """,
        TypeMismatch,
    )
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_powmod_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


valid_list = [
    """
FOO: constant(uint256) = 3
BAR: constant(uint256) = 5
BAZ: constant(uint256) = pow_mod256(FOO, BAR)

@external
def foo():
    a: uint256 = BAZ
    """
]


@pytest.mark.parametrize("code", valid_list)
def test_powmod_pass(code):
    assert compile_code(code) is not None
