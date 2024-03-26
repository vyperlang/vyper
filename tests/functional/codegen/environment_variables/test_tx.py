def test_tx_gasprice(get_contract, revm_env):
    code = """
@external
def tx_gasprice() -> uint256:
    return tx.gasprice
"""
    revm_env.set_balance(revm_env.deployer, 10**20)
    c = get_contract(code)
    for i in range(10):
        assert c.tx_gasprice(call={"gasPrice": 10**i}) == 10**i
