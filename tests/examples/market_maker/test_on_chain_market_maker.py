import pytest
from viper import compiler
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract, assert_tx_failed
from viper.exceptions import StructureException, VariableDeclarationException, InvalidTypeException

@pytest.fixture
def market_maker():
    t.languages['viper'] = compiler.Compiler()
    contract_code = open('examples/market_maker/on_chain_market_maker.v.py').read()
    return s.contract(contract_code, language='viper')

TOKEN_NAME = "Vipercoin"
TOKEN_SYMBOL = "FANG"
TOKEN_DECIMALS = 18
TOKEN_INITIAL_SUPPLY = (21 * 10 ** 6)
TOKEN_TOTAL_SUPPLY = TOKEN_INITIAL_SUPPLY * (10 ** TOKEN_DECIMALS)

@pytest.fixture
def erc20():
    t.languages['viper'] = compiler.Compiler()
    contract_code = open('examples/tokens/ERC20.v.py').read()
    return s.contract(contract_code, language='viper', args=[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY])


def test_initial_statet(market_maker):
    assert market_maker.get_total_eth_qty() == 0
    assert market_maker.get_total_token_qty() == 0
    assert market_maker.get_invariant() == 0
    assert u.remove_0x_head(market_maker.get_owner()) == '0000000000000000000000000000000000000000'


def test_initiate(market_maker, erc20, assert_tx_failed):
    erc20.approve(market_maker.address, 2*10**18)
    market_maker.initiate(erc20.address, 1*10**18, value=2*10**18)
    assert market_maker.get_total_eth_qty() == 2*10**18
    assert market_maker.get_total_token_qty() == 1*10**18
    assert market_maker.get_invariant() == 2*10**18
    assert u.remove_0x_head(market_maker.get_owner()) == t.a0.hex()
    t.s = s
    # Initiate cannot be called twice
    assert_tx_failed(t, lambda: market_maker.initiate(erc20.address, 1*10**18, value=2*10**18))


def test_eth_to_tokens(market_maker, erc20):
    erc20.approve(market_maker.address, 2*10**18)
    market_maker.initiate(erc20.address, 1*10**18, value=2*10**18)
    assert erc20.balanceOf(market_maker.address) == 1000000000000000000
    assert erc20.balanceOf(t.a1) == 0
    market_maker.eth_to_tokens(value=100, sender=t.k1)
    assert erc20.balanceOf(market_maker.address) == 0
    assert erc20.balanceOf(t.a1) == 1000000000000000000
    assert market_maker.get_total_token_qty() == 0


def test_tokens_to_eth(market_maker, erc20):
    erc20.approve(market_maker.address, 2*10**18)
    market_maker.initiate(erc20.address, 1*10**18, value=2*10**18)
    assert s.head_state.get_balance(market_maker.address) == 2000000000000000000
    assert s.head_state.get_balance(t.a1) == 999999999999999999999900
    market_maker.tokens_to_eth(100, sender=t.k1)
    assert s.head_state.get_balance(market_maker.address) == 1
    assert s.head_state.get_balance(t.a1) == 1000001999999999999999899
    assert market_maker.get_total_eth_qty() == 1


def test_owner_withdraw(market_maker, erc20, assert_tx_failed):
    erc20.approve(market_maker.address, 2*10**18)
    market_maker.initiate(erc20.address, 1*10**18, value=2*10**18)
    assert s.head_state.get_balance(t.a0) == 999992000000000000000000
    assert erc20.balanceOf(t.a0) == 20999999000000000000000000
    t.s = s
    # Only owner can call owner_withdraw
    assert_tx_failed(t, lambda: market_maker.owner_withdraw(sender=t.k1))
    market_maker.owner_withdraw()
    assert s.head_state.get_balance(t.a0) == 999994000000000000000000
    assert erc20.balanceOf(t.a0) == 21000000000000000000000000
