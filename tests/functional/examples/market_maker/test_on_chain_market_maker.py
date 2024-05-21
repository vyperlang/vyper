import pytest
from eth_utils import to_wei

from tests.utils import ZERO_ADDRESS

TOKEN_NAME = "Vypercoin"
TOKEN_SYMBOL = "FANG"
TOKEN_DECIMALS = 18
TOKEN_INITIAL_SUPPLY = 21 * 10**6
TOKEN_TOTAL_SUPPLY = TOKEN_INITIAL_SUPPLY * (10**TOKEN_DECIMALS)


@pytest.fixture(scope="module")
def erc20(get_contract):
    with open("examples/tokens/ERC20.vy") as f:
        contract_code = f.read()
    return get_contract(
        contract_code, *[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY]
    )


@pytest.fixture(scope="module")
def market_maker(get_contract, erc20):
    with open("examples/market_maker/on_chain_market_maker.vy") as f:
        contract_code = f.read()
    return get_contract(contract_code)


def test_initial_state(market_maker):
    assert market_maker.totalEthQty() == 0
    assert market_maker.totalTokenQty() == 0
    assert market_maker.invariant() == 0
    assert market_maker.owner() == ZERO_ADDRESS


def test_initiate(env, market_maker, erc20, tx_failed):
    a0 = env.accounts[0]
    ether, ethers = to_wei(1, "ether"), to_wei(2, "ether")
    env.set_balance(a0, ethers * 2)
    erc20.approve(market_maker.address, ethers)
    market_maker.initiate(erc20.address, ether, value=ethers)
    assert market_maker.totalEthQty() == ethers
    assert market_maker.totalTokenQty() == ether
    assert market_maker.invariant() == 2 * 10**36
    assert market_maker.owner() == a0
    assert erc20.name() == TOKEN_NAME
    assert erc20.decimals() == TOKEN_DECIMALS

    # Initiate cannot be called twice
    with tx_failed():
        market_maker.initiate(erc20.address, ether, value=ethers)


def test_eth_to_tokens(env, market_maker, erc20):
    a0, a1 = env.accounts[:2]
    env.set_balance(a0, to_wei(2, "ether"))
    erc20.approve(market_maker.address, to_wei(2, "ether"))
    market_maker.initiate(erc20.address, to_wei(1, "ether"), value=to_wei(2, "ether"))
    assert erc20.balanceOf(market_maker.address) == to_wei(1, "ether")
    assert erc20.balanceOf(a1) == 0
    assert market_maker.totalTokenQty() == to_wei(1, "ether")
    assert market_maker.totalEthQty() == to_wei(2, "ether")

    env.set_balance(a1, 100)
    market_maker.ethToTokens(value=100, sender=a1)
    assert erc20.balanceOf(market_maker.address) == 999999999999999950
    assert erc20.balanceOf(a1) == 50
    assert market_maker.totalTokenQty() == 999999999999999950
    assert market_maker.totalEthQty() == 2000000000000000100


def test_tokens_to_eth(env, market_maker, erc20):
    a1 = env.accounts[1]
    a1_balance_before = to_wei(2, "ether")
    env.set_balance(a1, a1_balance_before)

    erc20.transfer(a1, to_wei(2, "ether"))
    erc20.approve(market_maker.address, to_wei(2, "ether"), sender=a1)
    market_maker.initiate(erc20.address, to_wei(1, "ether"), value=to_wei(2, "ether"), sender=a1)
    assert env.get_balance(market_maker.address) == to_wei(2, "ether")
    # sent 2 eth, with initiate.
    assert env.get_balance(a1) == a1_balance_before - to_wei(2, "ether")
    assert market_maker.totalTokenQty() == to_wei(1, "ether")

    erc20.approve(market_maker.address, to_wei(1, "ether"), sender=a1)
    market_maker.tokensToEth(to_wei(1, "ether"), sender=a1)
    # 1 eth less in market.
    assert env.get_balance(market_maker.address) == to_wei(1, "ether")
    # got 1 eth back, for trade.
    assert env.get_balance(a1) == a1_balance_before - to_wei(1, "ether")
    # Tokens increased by 1
    assert market_maker.totalTokenQty() == to_wei(2, "ether")
    assert market_maker.totalEthQty() == to_wei(1, "ether")


def test_owner_withdraw(env, market_maker, erc20, tx_failed):
    a0, a1 = env.accounts[:2]
    a0_balance_before = to_wei(10, "ether")
    env.set_balance(a0, a0_balance_before)
    # Approve 2 eth transfers.
    erc20.approve(market_maker.address, to_wei(2, "ether"))
    # Initiate market with 2 eth value.
    market_maker.initiate(erc20.address, to_wei(1, "ether"), value=to_wei(2, "ether"))
    # 2 eth was sent to market_maker contract.
    assert env.get_balance(a0) == a0_balance_before - to_wei(2, "ether")
    # a0's balance is locked up in market_maker contract.
    assert erc20.balanceOf(a0) == TOKEN_TOTAL_SUPPLY - to_wei(1, "ether")

    # Only owner can call ownerWithdraw
    with tx_failed():
        market_maker.ownerWithdraw(sender=a1)
    market_maker.ownerWithdraw()
    assert env.get_balance(a0) == a0_balance_before  # Eth balance restored.
    assert erc20.balanceOf(a0) == TOKEN_TOTAL_SUPPLY  # Tokens returned to a0.
