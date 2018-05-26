def test_block_number(get_contract_with_gas_estimation, w3):
    w3.testing.mine(1)

    block_number_code = """
@public
def block_number() -> uint256:
    return block.number
"""
    c = get_contract_with_gas_estimation(block_number_code)
    assert c.block_number() == 2


def test_blockhash(get_contract_with_gas_estimation, w3):
    w3.testing.mine(1)

    block_number_code = """
@public
def prev() -> bytes32:
    return block.prevhash

@public
def previous_blockhash() -> bytes32:
    return blockhash(block.number - 1)
"""
    c = get_contract_with_gas_estimation(block_number_code)
    assert c.prev() == c.previous_blockhash()
