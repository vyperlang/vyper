import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation


def test_block_number():
    block_number_code = """
@public
def block_number() -> num:
    return block.number
"""
    c = get_contract_with_gas_estimation(block_number_code)
    c.block_number() == 2
