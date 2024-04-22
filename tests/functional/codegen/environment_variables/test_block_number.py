def test_block_number(get_contract, env, compiler_settings, output_formats):
    block_number_code = """
@external
def block_number() -> uint256:
    return block.number
    """
    c = get_contract(block_number_code)

    assert c.block_number() == 1
    env.time_travel()
    assert c.block_number() == 2
