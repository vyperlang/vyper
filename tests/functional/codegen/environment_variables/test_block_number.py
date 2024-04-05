def test_block_number(get_contract, env, compiler_settings, output_formats):
    block_number_code = """
@external
def block_number() -> uint256:
    return block.number
    """
    c = get_contract(block_number_code)

    assert c.block_number() == 1
    env.time_travel()
    c = env.deploy_source(block_number_code, output_formats, compiler_settings)
    assert c.block_number() == 2
