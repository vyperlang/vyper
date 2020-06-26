import pytest
from eth_utils import keccak

import vyper


@pytest.fixture
def create_token(get_contract):
    with open("examples/tokens/ERC20.vy") as f:
        code = f.read()

    def create_token():
        return get_contract(code, *["VyperCoin", "FANG", 0, 0])

    return create_token


@pytest.fixture
def create_exchange(w3, get_contract):
    with open("examples/tokenswap/Exchange.vy") as f:
        code = f.read()

    def create_exchange(token, registry):
        exchange = get_contract(code, *[token.address, registry.address])
        # NOTE: Must initialize exchange to register it with registry
        exchange.initialize(transact={"from": w3.eth.accounts[0]})
        return exchange

    return create_exchange


@pytest.fixture
def registry(get_contract):
    with open("examples/tokenswap/Exchange.vy") as f:
        code = f.read()

    exchange_interface = vyper.compile_code(code, output_formats=["bytecode_runtime"])
    exchange_deployed_bytecode = exchange_interface["bytecode_runtime"]

    with open("examples/tokenswap/Registry.vy") as f:
        code = f.read()

    # NOTE: We deploy the registry with the hash of the exchange's expected deployment bytecode
    return get_contract(code, keccak(hexstr=exchange_deployed_bytecode))


def test_exchange(w3, registry, create_token, create_exchange):
    a = w3.eth.accounts[0]
    token1 = create_token()
    exchange1 = create_exchange(token1, registry)
    token2 = create_token()
    exchange2 = create_exchange(token2, registry)

    # user has token 1
    token1.mint(a, 1, transact={"from": a})
    # exchange has token 2
    token2.mint(exchange2.address, 1, transact={"from": a})
    # So approval doesn't fail for transferFrom
    token1.approve(exchange1.address, 1, transact={"from": a})

    # trade token 1 for token 2
    assert token1.balanceOf(a) == 1
    assert token2.balanceOf(a) == 0
    registry.trade(token1.address, token2.address, 1, transact={"from": a})
    assert token1.balanceOf(a) == 0
    assert token2.balanceOf(a) == 1
