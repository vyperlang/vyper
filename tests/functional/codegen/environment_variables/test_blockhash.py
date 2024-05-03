def test_blockhash(get_contract):
    block_number_code = """
@external
def prev() -> bytes32:
    return block.prevhash

@external
def previous_blockhash() -> bytes32:
    return blockhash(block.number - 1)
"""
    c = get_contract(block_number_code)
    assert c.prev() == c.previous_blockhash()


def test_negative_blockhash(assert_compile_failed, get_contract):
    code = """
@external
def foo() -> bytes32:
    return blockhash(-1)
"""
    assert_compile_failed(lambda: get_contract(code))


def test_too_old_blockhash(tx_failed, get_contract, env):
    env.block_number += 257
    code = """
@external
def get_50_blockhash() -> bytes32:
    return blockhash(block.number - 257)
"""
    c = get_contract(code)
    with tx_failed():
        c.get_50_blockhash()


def test_non_existing_blockhash(tx_failed, get_contract):
    code = """
@external
def get_future_blockhash() -> bytes32:
    return blockhash(block.number + 1)
"""
    c = get_contract(code)
    with tx_failed():
        c.get_future_blockhash()
