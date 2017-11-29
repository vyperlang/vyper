import pytest
from viper.exceptions import StructureException

from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_invalid_if_both_public_and_internal(assert_compile_failed):
    code = """
@public
@private
def foo():
    x = 1
"""

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), StructureException)


def test_invalid_if_visibility_isnt_declared(assert_compile_failed):
    code = """
def foo():
    x = 1
"""

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), StructureException)
