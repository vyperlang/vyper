import pytest
from eth_utils import keccak

import vyper
from vyper.compiler.settings import Settings


@pytest.fixture
def create_token(get_contract):
    with open("examples/tokens/ERC20.vy") as f:
        code = f.read()

    def create_token():
        return get_contract(code, *["VyperCoin", "FANG", 0, 0])

    return create_token


@pytest.fixture
def create_exchange(w3, get_contract):
    with open("examples/factory/Exchange.vy") as f:
        code = f.read()

    def create_exchange(token, factory):
        exchange = get_contract(code, *[token.address, factory.address])
        # NOTE: Must initialize exchange to register it with factory
        exchange.initialize(transact={"from": w3.eth.accounts[0]})
        return exchange

    return create_exchange


@pytest.fixture
def factory(get_contract, optimize):
    with open("examples/factory/Exchange.vy") as f:
        code = f.read()

    exchange_interface = vyper.compile_code(
        code, output_formats=["bytecode_runtime"], settings=Settings(optimize=optimize)
    )
    exchange_deployed_bytecode = exchange_interface["bytecode_runtime"]

    with open("examples/factory/Factory.vy") as f:
        code = f.read()

    # NOTE: We deploy the factory with the hash of the exchange's expected deployment bytecode
    return get_contract(code, keccak(hexstr=exchange_deployed_bytecode))


def test_exchange(w3, factory, create_token, create_exchange):
    a = w3.eth.accounts[0]
    token1 = create_token()
    exchange1 = create_exchange(token1, factory)
    token2 = create_token()
    exchange2 = create_exchange(token2, factory)

    # user has token 1
    token1.mint(a, 1, transact={"from": a})
    # exchange has token 2
    token2.mint(exchange2.address, 1, transact={"from": a})
    # So approval doesn't fail for transferFrom
    token1.approve(exchange1.address, 1, transact={"from": a})

    # trade token 1 for token 2
    assert token1.balanceOf(a) == 1
    assert token2.balanceOf(a) == 0
    factory.trade(token1.address, token2.address, 1, transact={"from": a})
    assert token1.balanceOf(a) == 0
    assert token2.balanceOf(a) == 1
