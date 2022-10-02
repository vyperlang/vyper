def test_block_number(w3_get_contract_with_gas_estimation, w3):
    block_number_code = """
@external
def block_number() -> uint256:
    return block.number
    """
    c = w3_get_contract_with_gas_estimation(block_number_code)

    assert c.block_number() == 1
    w3.testing.mine(1)
    assert c.block_number() == 2
