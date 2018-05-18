
def test_block_number(get_contract_with_gas_estimation, w3):
    block_number_code = """
@public
def block_number() -> int128:
    return block.number
    """
    c = get_contract_with_gas_estimation(block_number_code)

    assert c.block_number() == 1
    w3.testing.mine(1)
    assert c.block_number() == 2
