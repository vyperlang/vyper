import pytest


def test_assert_refund(t, get_contract_with_gas_estimation):
    code = """
@public
def foo():
    assert 1 == 2
"""
    c = get_contract_with_gas_estimation(code)
    pre_balance = t.s.head_state.get_balance(t.a0)
    with pytest.raises(t.TransactionFailed):
        c.foo(startgas=10**6, gasprice=10)
    post_balance = t.s.head_state.get_balance(t.a0)
    # Checks for gas refund from revert
    # 10**5 is added to account for gas used before the transactions fails
    assert pre_balance < post_balance + 10**5
