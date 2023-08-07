import pytest

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


good_code = [
    """
@external
@view
def foo(x: address):
    assert convert(
        raw_call(
            x,
            b'',
            max_outsize=32,
            is_static_call=True,
        ), uint256
    ) > 123, "vyper"
    """
]


@pytest.mark.parametrize("code", good_code)
def test_view_call_compiles(get_contract, code):
    get_contract(code)
