import pytest

from vyper.exceptions import FunctionDeclarationException


def test_constant_test(get_contract):
    constant_test = """
@external
@view
def foo() -> int128:
    return 5
    """

    c = get_contract(constant_test)
    assert c.foo() == 5

    print("Passed constant function test")


@pytest.mark.requires_evm_version("cancun")
def test_transient_test(get_contract):
    code = """
x: transient(uint256)

@external
@view
def foo() -> uint256:
    return self.x
    """
    c = get_contract(code)
    assert c.foo() == 0


def test_invalid_constant_and_payable(get_contract, assert_compile_failed):
    code = """
@external
@payable
@view
def foo() -> num:
    return 5
"""
    assert_compile_failed(lambda: get_contract(code), FunctionDeclarationException)
