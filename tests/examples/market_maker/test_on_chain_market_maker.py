import pytest
from viper import compiler


@pytest.fixture
def market_maker(t, chain):
    t.languages['viper'] = compiler.Compiler()
    contract_code = open('examples/market_maker/on_chain_market_maker.v.py').read()
    return chain.contract(contract_code, language='viper')


TOKEN_NAME = "Vipercoin"
TOKEN_SYMBOL = "FANG"
TOKEN_DECIMALS = 18
TOKEN_INITIAL_SUPPLY = (21 * 10 ** 6)
TOKEN_TOTAL_SUPPLY = TOKEN_INITIAL_SUPPLY * (10 ** TOKEN_DECIMALS)


@pytest.fixture
def erc20(t, chain):
    t.languages['viper'] = compiler.Compiler()
    contract_code = open('examples/tokens/vipercoin.v.py').read()
    return chain.contract(contract_code, language='viper', args=[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY])


def test_initial_statet(market_maker, utils):
    assert market_maker.get_total_eth_qty() == 0
    assert market_maker.get_total_token_qty() == 0
    assert market_maker.get_invariant() == 0
    assert utils.remove_0x_head(market_maker.get_owner()) == '0000000000000000000000000000000000000000'


def test_initiate(t, chain, utils, market_maker, erc20, assert_tx_failed):
    erc20.approve(market_maker.address, 2 * 10 ** 18)
    market_maker.initiate(erc20.address, 1 * 10 ** 18, value=2 * 10 ** 18)
    assert market_maker.get_total_eth_qty() == 2 * 10 ** 18
    assert market_maker.get_total_token_qty() == 1 * 10 ** 18
    assert market_maker.get_invariant() == 2 * 10 ** 36
    assert utils.remove_0x_head(market_maker.get_owner()) == t.a0.hex()
    t.s = chain
    # Initiate cannot be called twice
    assert_tx_failed(lambda: market_maker.initiate(erc20.address, 1 * 10 ** 18, value=2 * 10 ** 18))


def test_eth_to_tokens(t, market_maker, erc20):
    erc20.approve(market_maker.address, 2 * 10 ** 18)
    market_maker.initiate(erc20.address, 1 * 10 ** 18, value=2 * 10 ** 18)
    assert erc20.balanceOf(market_maker.address) == 1000000000000000000
    assert erc20.balanceOf(t.a1) == 0
    assert market_maker.get_total_token_qty() == 1000000000000000000
    assert market_maker.get_total_eth_qty() == 2000000000000000000
    market_maker.eth_to_tokens(value=100, sender=t.k1)
    assert erc20.balanceOf(market_maker.address) == 999999999999999950
    assert erc20.balanceOf(t.a1) == 50
    assert market_maker.get_total_token_qty() == 999999999999999950
    assert market_maker.get_total_eth_qty() == 2000000000000000100


def test_tokens_to_eth(t, chain, market_maker, erc20):
    erc20.transfer(t.a1, 1 * 10 ** 18)
    erc20.approve(market_maker.address, 2 * 10 ** 18)
    market_maker.initiate(erc20.address, 1 * 10**18, value=2 * 10 ** 18)
    assert chain.head_state.get_balance(market_maker.address) == 2000000000000000000
    assert chain.head_state.get_balance(t.a1) == 999999999999999999999900
    assert market_maker.get_total_token_qty() == 1000000000000000000
    erc20.approve(market_maker.address, 1 * 10 ** 18, sender=t.k1)
    market_maker.tokens_to_eth(1 * 10 ** 18, sender=t.k1)
    assert chain.head_state.get_balance(market_maker.address) == 1000000000000000000
    assert chain.head_state.get_balance(t.a1) == 1000000999999999999999900
    assert market_maker.get_total_token_qty() == 2000000000000000000
    assert market_maker.get_total_eth_qty() == 1000000000000000000


def test_owner_withdraw(t, chain, market_maker, erc20, assert_tx_failed):
    erc20.approve(market_maker.address, 2 * 10 ** 18)
    market_maker.initiate(erc20.address, 1 * 10 ** 18, value=2 * 10 ** 18)
    assert chain.head_state.get_balance(t.a0) == 999992000000000000000000
    assert erc20.balanceOf(t.a0) == 20999999000000000000000000
    t.s = chain
    # Only owner can call owner_withdraw
    assert_tx_failed(lambda: market_maker.owner_withdraw(sender=t.k1))
    market_maker.owner_withdraw()
    assert chain.head_state.get_balance(t.a0) == 999994000000000000000000
    assert erc20.balanceOf(t.a0) == 21000000000000000000000000
