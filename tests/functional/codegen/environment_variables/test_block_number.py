def test_block_number(get_contract_with_gas_estimation, env, optimize, output_formats):
    block_number_code = """
@external
def block_number() -> uint256:
    return block.number
    """
    c = get_contract_with_gas_estimation(block_number_code)

    assert c.block_number() == 1
    env.mine()
    c = env.deploy_source(block_number_code, optimize, output_formats)
    assert c.block_number() == 2
