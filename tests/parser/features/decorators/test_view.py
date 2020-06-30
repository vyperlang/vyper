from vyper.exceptions import FunctionDeclarationException


def test_constant_test(get_contract_with_gas_estimation_for_constants):
    constant_test = """
@external
@view
def foo() -> int128:
    return 5
    """

    c = get_contract_with_gas_estimation_for_constants(constant_test)
    assert c.foo() == 5

    print("Passed constant function test")


def test_invalid_constant_and_payable(
    get_contract_with_gas_estimation_for_constants, assert_compile_failed
):
    code = """
@external
@payable
@view
def foo() -> num:
    return 5
"""
    assert_compile_failed(
        lambda: get_contract_with_gas_estimation_for_constants(code), FunctionDeclarationException
    )
