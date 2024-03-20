import pytest


@pytest.fixture
def market_maker(get_contract):
    with open("examples/market_maker/on_chain_market_maker.vy") as f:
        contract_code = f.read()
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


def test_initial_state(market_maker):
    assert market_maker.totalEthQty() == 0
    assert market_maker.totalTokenQty() == 0
    assert market_maker.invariant() == 0
    assert market_maker.owner() is None


def test_initiate(w3, market_maker, erc20, tx_failed):
    a0 = w3.eth.accounts[0]
    ether, ethers = w3.to_wei(1, "ether"), w3.to_wei(2, "ether")
    erc20.approve(market_maker.address, ethers, transact={})
    market_maker.initiate(erc20.address, ether, transact={"value": ethers})
    assert market_maker.totalEthQty() == ethers
    assert market_maker.totalTokenQty() == ether
    assert market_maker.invariant() == 2 * 10**36
    assert market_maker.owner() == a0
    assert erc20.name() == TOKEN_NAME
    assert erc20.decimals() == TOKEN_DECIMALS

    # Initiate cannot be called twice
    with tx_failed():
        market_maker.initiate(erc20.address, ether, transact={"value": ethers})


def test_eth_to_tokens(w3, market_maker, erc20):
    a1 = w3.eth.accounts[1]
    erc20.approve(market_maker.address, w3.to_wei(2, "ether"), transact={})
    market_maker.initiate(
        erc20.address, w3.to_wei(1, "ether"), transact={"value": w3.to_wei(2, "ether")}
    )
    assert erc20.balanceOf(market_maker.address) == w3.to_wei(1, "ether")
    assert erc20.balanceOf(a1) == 0
    assert market_maker.totalTokenQty() == w3.to_wei(1, "ether")
    assert market_maker.totalEthQty() == w3.to_wei(2, "ether")

    market_maker.ethToTokens(transact={"value": 100, "from": a1})
    assert erc20.balanceOf(market_maker.address) == 999999999999999950
    assert erc20.balanceOf(a1) == 50
    assert market_maker.totalTokenQty() == 999999999999999950
    assert market_maker.totalEthQty() == 2000000000000000100


def test_tokens_to_eth(w3, market_maker, erc20):
    a1 = w3.eth.accounts[1]
    a1_balance_before = w3.eth.get_balance(a1)

    erc20.transfer(a1, w3.to_wei(2, "ether"), transact={})
    erc20.approve(market_maker.address, w3.to_wei(2, "ether"), transact={"from": a1})
    market_maker.initiate(
        erc20.address, w3.to_wei(1, "ether"), transact={"value": w3.to_wei(2, "ether"), "from": a1}
    )
    assert w3.eth.get_balance(market_maker.address) == w3.to_wei(2, "ether")
    # sent 2 eth, with initiate.
    assert w3.eth.get_balance(a1) == a1_balance_before - w3.to_wei(2, "ether")
    assert market_maker.totalTokenQty() == w3.to_wei(1, "ether")

    erc20.approve(market_maker.address, w3.to_wei(1, "ether"), transact={"from": a1})
    market_maker.tokensToEth(w3.to_wei(1, "ether"), transact={"from": a1})
    # 1 eth less in market.
    assert w3.eth.get_balance(market_maker.address) == w3.to_wei(1, "ether")
    # got 1 eth back, for trade.
    assert w3.eth.get_balance(a1) == a1_balance_before - w3.to_wei(1, "ether")
    # Tokens increased by 1
    assert market_maker.totalTokenQty() == w3.to_wei(2, "ether")
    assert market_maker.totalEthQty() == w3.to_wei(1, "ether")


def test_owner_withdraw(w3, market_maker, erc20, tx_failed):
    a0, a1 = w3.eth.accounts[:2]
    a0_balance_before = w3.eth.get_balance(a0)
    # Approve 2 eth transfers.
    erc20.approve(market_maker.address, w3.to_wei(2, "ether"), transact={})
    # Initiate market with 2 eth value.
    market_maker.initiate(
        erc20.address, w3.to_wei(1, "ether"), transact={"value": w3.to_wei(2, "ether")}
    )
    # 2 eth was sent to market_maker contract.
    assert w3.eth.get_balance(a0) == a0_balance_before - w3.to_wei(2, "ether")
    # a0's balance is locked up in market_maker contract.
    assert erc20.balanceOf(a0) == TOKEN_TOTAL_SUPPLY - w3.to_wei(1, "ether")

    # Only owner can call ownerWithdraw
    with tx_failed():
        market_maker.ownerWithdraw(transact={"from": a1})
    market_maker.ownerWithdraw(transact={})
    assert w3.eth.get_balance(a0) == a0_balance_before  # Eth balance restored.
    assert erc20.balanceOf(a0) == TOKEN_TOTAL_SUPPLY  # Tokens returned to a0.
