import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_basic_in_list():
    code = """
def testin(x: num) -> bool:
    s = [1, 2, 3, 4]
    if x in s:
        return True
    return False
    """

    c = get_contract(code)

    assert c.testin(1) is True
    assert c.testin(2) is True
    assert c.testin(3) is True
    assert c.testin(4) is True
    assert c.testin(5) is False
    assert c.testin(0) is False
    assert c.testin(-1) is False


# def test_cmp_in_list():
#     code = """
# def in_test(x: num) -> bool:
#     if x in [9, 7, 6, 5]:
#         return True
#     return False
#     """

#     c = get_contract(code)

#     assert c.in_test(1) == True
#     assert c.in_test(5) == False
