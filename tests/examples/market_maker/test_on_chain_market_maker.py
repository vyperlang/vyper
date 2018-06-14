import pytest


@pytest.fixture
def market_maker(get_contract):
    with open('examples/market_maker/on_chain_market_maker.vy') as f:
        contract_code = f.read()
    return get_contract(contract_code)


TOKEN_NAME = b"Vypercoin"
TOKEN_SYMBOL = b"FANG"
TOKEN_DECIMALS = 18
TOKEN_INITIAL_SUPPLY = (21 * 10 ** 6)
TOKEN_TOTAL_SUPPLY = TOKEN_INITIAL_SUPPLY * (10 ** TOKEN_DECIMALS)


@pytest.fixture
def erc20(get_contract):
    with open('examples/tokens/vypercoin.vy') as f:
        contract_code = f.read()
    return get_contract(contract_code, *[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY])


def test_initial_statet(market_maker):
    assert market_maker.total_eth_qty() == 0
    assert market_maker.total_token_qty() == 0
    assert market_maker.invariant() == 0
    assert market_maker.owner() is None


def test_initiate(w3, market_maker, erc20, assert_tx_failed):
    a0 = w3.eth.accounts[0]
    erc20.approve(market_maker.address, 2 * 10**18, transact={})
    market_maker.initiate(erc20.address, 1 * 10**18, transact={'value': 2 * 10**18})
    assert market_maker.total_eth_qty() == 2 * 10**18
    assert market_maker.total_token_qty() == 1 * 10**18
    assert market_maker.invariant() == 2 * 10**36
    assert market_maker.owner() == a0
    assert erc20.name().split(b'\0', 1)[0] == TOKEN_NAME
    assert erc20.decimals() == TOKEN_DECIMALS

    # Initiate cannot be called twice
    assert_tx_failed(lambda: market_maker.initiate(erc20.address, 1 * 10**18, transact={'value': 2 * 10**18}))


def test_eth_to_tokens(w3, market_maker, erc20):
    a1 = w3.eth.accounts[1]
    erc20.approve(market_maker.address, 2 * 10**18, transact={})
    market_maker.initiate(erc20.address, 1 * 10**18, transact={'value': 2 * 10**18})
    assert erc20.balanceOf(market_maker.address) == 1000000000000000000
    assert erc20.balanceOf(a1) == 0
    assert market_maker.total_token_qty() == 1000000000000000000
    assert market_maker.total_eth_qty() == 2000000000000000000

    market_maker.eth_to_tokens(transact={'value': 100, 'from': a1})
    assert erc20.balanceOf(market_maker.address) == 999999999999999950
    assert erc20.balanceOf(a1) == 50
    assert market_maker.total_token_qty() == 999999999999999950
    assert market_maker.total_eth_qty() == 2000000000000000100


def test_tokens_to_eth(w3, tester, market_maker, erc20):
    a1 = w3.eth.accounts[1]
    erc20.transfer(a1, 2 * 10**18, transact={})
    erc20.approve(market_maker.address, 2 * 10**18, transact={'from': a1})
    market_maker.initiate(erc20.address, 1 * 10**18, transact={'value': 2 * 10**18, 'from': a1})
    assert w3.eth.getBalance(market_maker.address) == 2000000000000000000
    assert w3.eth.getBalance(a1) == 999997999999999999999900
    assert market_maker.total_token_qty() == 1000000000000000000

    erc20.approve(market_maker.address, 1 * 10**18, transact={'from': a1})
    market_maker.tokens_to_eth(1 * 10**18, transact={'from': a1})
    assert w3.eth.getBalance(market_maker.address) == 1000000000000000000
    assert w3.eth.getBalance(a1) == 999998999999999999999900
    assert market_maker.total_token_qty() == 2000000000000000000
    assert market_maker.total_eth_qty() == 1000000000000000000


def test_owner_withdraw(w3, tester, market_maker, erc20, assert_tx_failed):
    a0, a1 = w3.eth.accounts[:2]
    erc20.approve(market_maker.address, 2 * 10**18, transact={})
    market_maker.initiate(erc20.address, 1 * 10**18, transact={'value': 2 * 10**18})
    assert w3.eth.getBalance(a0) == 999994000000000000000000
    assert erc20.balanceOf(a0) == 20999999000000000000000000

    # Only owner can call owner_withdraw
    assert_tx_failed(lambda: market_maker.owner_withdraw(transact={'from': a1}))
    market_maker.owner_withdraw(transact={})
    assert w3.eth.getBalance(a0) == 999996000000000000000000
    assert erc20.balanceOf(a0) == 21000000000000000000000000
