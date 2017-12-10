def test_block_number(get_contract_with_gas_estimation, fake_tx):
    fake_tx()

    block_number_code = """
@public
def block_number() -> num:
    return block.number
"""
    c = get_contract_with_gas_estimation(block_number_code)
    assert c.block_number() == 2
