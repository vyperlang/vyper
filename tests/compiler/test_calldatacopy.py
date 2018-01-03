

def test_calldatacopy(get_contract_from_lll):
    lll = ['calldatacopy', 32, 0, ['calldatasize']]
    get_contract_from_lll(lll)
