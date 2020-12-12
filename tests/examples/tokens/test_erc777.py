# Author: Takayuki Jimba (@yudetamago), Ryuya Nakamura (@nrryuya)
# Modified from Open Zeppelin's ERC-777 tests:
# https://github.com/OpenZeppelin/openzeppelin-contracts/blob/master/test/token/ERC777/ERC777.test.js
import pytest
from web3.exceptions import ValidationError

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
MAX_UINT256 = (2 ** 256) - 1  # Max uint256 value
TOKEN_NAME = "Vypercoin"
TOKEN_SYMBOL = "FANG"
TOKEN_DECIMALS = 18
TOKEN_INITIAL_SUPPLY = 10000



@pytest.fixture
def c(get_contract, w3):
    with open("examples/tokens/ERC777.vy") as f:
        code = f.read()
    c = get_contract(code, *[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY])
    return c


@pytest.fixture
def c_bad(get_contract, w3):
    # Bad contract is used for overflow checks on totalSupply corrupted
    with open("examples/tokens/ERC777.vy") as f:
        code = f.read()
    bad_code = code.replace("self.total_supply += _value", "",).replace(
        "self.total_supply -= _value", ""
    )
    c = get_contract(bad_code, *[TOKEN_NAME, TOKEN_SYMBOL, TOKEN_DECIMALS, TOKEN_INITIAL_SUPPLY])
    return c


@pytest.fixture
def get_log_args(get_logs):
    def get_log_args(tx_hash, c, event_name):
        logs = get_logs(tx_hash, c, event_name)
        assert len(logs) > 0
        args = logs[0].args
        return args

    return get_log_args


def test_default_operators(c, w3, assert_tx_failed):
    funder, holder, operator_a, operator_b, new_operator, anyone = w3.eth.accounts[:6]
    # TODO
    # _approve: when the owner is the zero address, revert
    assert_tx_failed(c.approveInternal(ZERO_ADDRESS, anyone, TOKEN_INITIAL_SUPPLY))


# TODO
def test_authorized_operator_event(c, w3):
    pass


def test_basic_information(c, w3):
    funder, holder, operator_a, operator_b, new_operator, anyone = w3.eth.accounts[:6]
    operators = [operator_a, operator_b]

    assert c.name() == TOKEN_NAME
    assert c.symbol == TOKEN_SYMBOL
    assert c.granularity() == 1
    # returns the default operators
    assert c.defaultOperators() == operators
    # default operators are operators for all accounts
    for operator in operators:
        assert c.isOperatorFor(operator, anyone) == True
    assert c.totalSupply() == TOKEN_INITIAL_SUPPLY
    assert c.decimals() == 18
    # TODO: check that interfaces are registered in registry
         

def test_balanceOf(c, w3):
    funder, holder, operator_a, operator_b, new_operator, anyone = w3.eth.accounts[:6]

    # for an account with no tokens, return zero
    assert c.balanceOf(anyone) == 0
    # for an account with tokens, return their balance
    assert c.balanceOf(holder) == TOKEN_INITIAL_SUPPLY


# TODO
def test_behave_like_erc777(c, w3):
    pass


def test_operator_management(c, w3, assert_tx_failed, get_logs):
    funder, holder, operator_a, operator_b, new_operator, anyone = w3.eth.accounts[:6]
    operators = [operator_a, operator_b]

    # accounts are their own operator
    assert c.isOperatorFor(holder, holder) == True
    
    # reverts when self-authorizing
    assert_tx_failed(lambda: c.authorizeOperator(holder, transact={'from': holder}))
    
    # reverts when self-revoking
    assert_tx_failed(lambda: c.revokeOperator(holder, transact={'from': holder}))
    
    # non-operators can be revoked
    assert c.isOperatorFor(new_operator, holder)) == False
    tx_hash = c.revokeOperator(new_operator, transact={'from': holder})
    logs = get_logs(tx_hash, c, "RevokedOperator")
    assert len(logs) > 0
    args = logs[0].args
    assert args.operator == new_operator
    assert args.tokenHolder == holder
    assert c.isOperatorFor(new_operator, holder)) == False
    
    # non-operators can be authorized
    assert c.isOperatorFor(new_operator, holder)) == False
    tx_hash = c.authorizeOperator(new_operator, transact={'from': holder})
    logs = get_logs(tx_hash, c, "AuthorizedOperator")
    assert len(logs) > 0
    args = logs[0].args
    assert args.operator == new_operator
    assert args.tokenHolder == holder
    assert c.isOperatorFor(new_operator, holder)) == True

    # new operators
    
    c.authorizeOperator(new_operator, transact={'from': holder})
    
    # are not added to the default operators list
    assert c.defaultOperators() == operators
    
    # can be re-authorized
    tx_hash = c.authorizeOperator(new_operator, transact={'from': holder})
    logs = get_logs(tx_hash, c, "AuthorizedOperator")
    assert len(logs) > 0
    args = logs[0].args
    assert args.operator == new_operator
    assert args.tokenHolder == holder
    assert c.isOperatorFor(new_operator, holder) == True

    # Can be revoked
    tx_hash = c.revokeOperator(new_operator, transact={'from': holder})
    logs = get_logs(tx_hash, c, "RevokedOperator")
    assert len(logs) > 0
    args = logs[0].args
    assert args.operator == new_operator
    assert args.tokenHolder == holder
    assert c.isOperatorFor(new_operator, holder) == False

    # default operators

    # can be re-authorized
    tx_hash = c.authorizeOperator(operator_a, transact={'from': holder})
    logs = get_logs(tx_hash, c, "AuthorizedOperator")
    assert len(logs) > 0
    args = logs[0].args
    assert args.operator == operator_a
    assert args.tokenHolder == holder
    assert c.isOperatorFor(operator_a, holder) == True
    
    # Can be revoked
    tx_hash = c.revokeOperator(operator_a, transact={'from': holder})
    logs = get_logs(tx_hash, c, "RevokedOperator")
    assert len(logs) > 0
    args = logs[0].args
    assert args.operator == operator_a
    assert args.tokenHolder == holder
    assert c.isOperatorFor(operator_a, holder) == False

    # Cannot be revoked for themselves
    assert_tx_failed(lambda: c.revokeOperator(operator_a, transact={'from': operator_a}))

    # with revoked default operator

    c.revokeOperator(operator_a, transact={'from': holder})

    # default operator is not revoked for other holders
    assert c.isOperatorFor(operator_a, anyone) == True

    # other default operators are not revoked
    assert c.isOperatorFor(operator_b, holder) == True

    # default operators list is not modified
    assert c.defaultOperators() == default_operators

    # revoked default operator can be re-authorized
    tx_hash = c.authorizeOperator(operator_a, transact={'from': holder})
    logs = get_logs(tx_hash, c, "AuthorizedOperator")
    assert len(logs) > 0
    args = log[0].args
    assert args.operator == operator_a
    assert args.tokenHolder == holder
    assert c.isOperatorFor(operator_a, holder) == True


def test_send_and_receive_hooks(c, w3, assert_tx_failed, get_logs):
    amount = 1
    operator = operator_a

    # tokensReceived
    sender == holder

    # with no ERC777TokensRecipient implementer

    # with contract recipient
    # TODO

    # send reverts
    assert_tx_failed(c.send(recipient, amount, data, transact={'from': holder}))

    # operatorSend reverts
    assert_tx_failed(c.operatorSend(sender, recipient, amount, data, operatorData, transact={'from': operator}))
    
    # mint (internal) reverts
    assert_tx_failed(c.mintInternal(recipient, amount, data, operatorData, transact={'from': operator}))

    # (ERC20) transfer succeed
    assert c.transfer(recipient, amount, transact={'from': holder})

    # (ERC20) transferFrom succeeds
    approved = anyone
    c.approve(approved, amount, transact={'from': sender})
    c.transferFrom(sender, recipient, amount, {'from': approved})

    # with ERC777TokensRecipient implementer

    # with contract as implementer for an externally owned account
    # TODO

    # with contract as implementer for another contract
    # TODO

    # with contract as implementer for itself
    # TODO