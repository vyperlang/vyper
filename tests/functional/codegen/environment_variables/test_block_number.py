from pyrevm import EVM, BlockEnv, Env


def test_block_number(get_contract_with_gas_estimation, revm_env, optimize, output_formats):
    block_number_code = """
@external
def block_number() -> uint256:
    return block.number
    """
    c = get_contract_with_gas_estimation(block_number_code)

    assert c.block_number() == 1
    revm_env.evm = EVM(env=Env(block=BlockEnv(number=2)))
    c = revm_env.deploy_source(block_number_code, optimize, output_formats)
    assert c.block_number() == 2
