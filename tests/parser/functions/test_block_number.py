def test_block_number(get_contract_with_gas_estimation, chain):
    chain.mine(1)

    block_number_code = """
@public
def block_number() -> num:
    return block.number
"""
    c = get_contract_with_gas_estimation(block_number_code)
    assert c.block_number() == 2
