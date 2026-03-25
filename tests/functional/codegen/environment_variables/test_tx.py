def test_tx_gasprice(get_contract, env):
    code = """
@external
def tx_gasprice() -> uint256:
    return tx.gasprice
"""
    env.set_balance(env.deployer, 10**20)
    c = get_contract(code)
    for i in range(10):
        assert c.tx_gasprice(gas_price=10**i) == 10**i
