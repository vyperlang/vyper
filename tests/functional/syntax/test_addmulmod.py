import pytest

from vyper import compile_code
from vyper.exceptions import TypeMismatch

fail_list = [
    (  # bad AST nodes given as arguments
        """
@external
def foo() -> uint256:
    return uint256_addmod(1.1, 1.2, 3.0)
    """,
        TypeMismatch,
    ),
    (  # bad AST nodes given as arguments
        """
@external
def foo() -> uint256:
    return uint256_mulmod(1.1, 1.2, 3.0)
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("code,exc", fail_list)
def test_add_mod_fail(assert_compile_failed, get_contract, code, exc):
    assert_compile_failed(lambda: get_contract(code), exc)


valid_list = [
    """
FOO: constant(uint256) = 3
BAR: constant(uint256) = 5
BAZ: constant(uint256) = 19
BAX: constant(uint256) = uint256_addmod(FOO, BAR, BAZ)
    """,
    """
FOO: constant(uint256) = 3
BAR: constant(uint256) = 5
BAZ: constant(uint256) = 19
BAX: constant(uint256) = uint256_mulmod(FOO, BAR, BAZ)
    """,
]


@pytest.mark.parametrize("code", valid_list)
def test_addmulmod_pass(code):
    assert compile_code(code) is not None
