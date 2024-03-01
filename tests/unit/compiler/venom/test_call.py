import pytest


@pytest.fixture
def market_maker(get_contract):
    contract_code = """
from ethereum.ercs import IERC20

unused: public(uint256)
token_address: IERC20

@external
@payable
def foo(token_addr: address, token_quantity: uint256):
    self.token_address = IERC20(token_addr)
    self.token_address.transferFrom(msg.sender, self, token_quantity)
"""
    return get_contract(contract_code)


TOKEN_NAME = "Vypercoin"
TOKEN_SYMBOL = "FANG"
TOKEN_DECIMALS = 18
TOKEN_INITIAL_SUPPLY = 21 * 10**6
TOKEN_TOTAL_SUPPLY = TOKEN_INITIAL_SUPPLY * (10**TOKEN_DECIMALS)


@pytest.fixture
def erc20(get_contract):
    with open("examples/tokens/ERC20.vy") as f:
        contract_code = f.read()
    return get_contract(
        contract_code, *[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY]
    )


def test_call(w3, market_maker, erc20, tx_failed):
    # a0 = w3.eth.accounts[0]
    ether, ethers = w3.to_wei(1, "ether"), w3.to_wei(2, "ether")
    erc20.approve(market_maker.address, ethers, transact={})
    assert erc20.name() == TOKEN_NAME
    assert erc20.decimals() == TOKEN_DECIMALS

    market_maker.foo(erc20.address, ether, transact={"value": ethers})
