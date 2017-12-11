from viper.exceptions import StructureException


def test_invalid_if_both_public_and_internal(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
@private
def foo():
    x = 1
"""

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), StructureException)


def test_invalid_if_visibility_isnt_declared(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
def foo():
    x = 1
"""

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), StructureException)
