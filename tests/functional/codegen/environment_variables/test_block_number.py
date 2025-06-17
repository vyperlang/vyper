def test_block_number(get_contract, env):
    block_number_code = """
@external
def block_number() -> uint256:
    return block.number
    """
    c = get_contract(block_number_code)

    assert c.block_number() == 1
    env.block_number += 1
    assert c.block_number() == 2
