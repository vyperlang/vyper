import pytest

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
