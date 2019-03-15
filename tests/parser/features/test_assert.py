from eth_tester.exceptions import (
    TransactionFailed,
)
import pytest

from vyper.exceptions import (
    ConstancyViolationException,
    StructureException,
)


def test_assert_refund(w3, get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@public
def foo():
    assert 1 == 2
    """
    c = get_contract_with_gas_estimation(code)
    a0 = w3.eth.accounts[0]
    pre_balance = w3.eth.getBalance(a0)
    tx_hash = c.foo(transact={'from': a0, 'gas': 10**6, 'gasPrice': 10})
    assert w3.eth.getTransactionReceipt(tx_hash)['status'] == 0
    # More info on receipt status:
    # https://github.com/ethereum/EIPs/blob/master/EIPS/eip-658.md#specification.
    post_balance = w3.eth.getBalance(a0)
    # Checks for gas refund from revert
    # 10**5 is added to account for gas used before the transactions fails
    assert pre_balance > post_balance


def test_assert_reason(w3, get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@public
def test(a: int128) -> int128:
    assert a > 1, "larger than one please"
    return 1 + a

@public
def test2(a: int128, b: int128) -> int128:
    c: int128 = 11
    assert a > 1, "a is not large enough"
    assert b == 1, "b may only be 1"
    return a + b + c

@public
def test3() :
    raise "An exception"
    """
    c = get_contract_with_gas_estimation(code)

    assert c.test(2) == 3
    with pytest.raises(TransactionFailed) as e_info:
        c.test(0)

    assert e_info.value.args[0] == 'larger than one please'
    # a = 0, b = 1
    with pytest.raises(TransactionFailed) as e_info:
        c.test2(0, 1)
    assert e_info.value.args[0] == 'a is not large enough'
    # a = 1, b = 0
    with pytest.raises(TransactionFailed) as e_info:
        c.test2(2, 2)
    assert e_info.value.args[0] == 'b may only be 1'
    # return correct value
    assert c.test2(5, 1) == 17

    with pytest.raises(TransactionFailed) as e_info:
        c.test3()
    assert e_info.value.args[0] == 'An exception'


def test_assert_reason_invalid(get_contract, assert_compile_failed):
    codes = [
        """
@public
def test(a: int128) -> int128:
    assert a > 1, ""
    return 1 + a
        """,
        # Must be a literal string.
        """
@public
def mint(_to: address, _value: uint256):
    assert msg.sender == self,minter
        """,
        # Raise must have a reason
        """
@public
def mint(_to: address, _value: uint256):
    raise
        """,
        # Raise reason must be string
        """
@public
def mint(_to: address, _value: uint256):
    raise 1
        """]

    for code in codes:
        assert_compile_failed(lambda: get_contract(code), StructureException)


def test_assert_no_effects(get_contract, assert_compile_failed, assert_tx_failed):
    code = """
@public
def ret1() -> int128:
    return 1
@public
def test():
    assert self.ret1() == 1
    """
    assert_compile_failed(lambda: get_contract(code), ConstancyViolationException)

    code = """
@private
def ret1() -> int128:
    return 1
@public
def test():
    assert self.ret1() == 1
    """
    assert_compile_failed(lambda: get_contract(code), ConstancyViolationException)

    code = """
@public
def test():
    assert raw_call(msg.sender, b'', outsize=1, gas=10, value=1000*1000) == 1
    """
    assert_compile_failed(lambda: get_contract(code), ConstancyViolationException)

    code = """
@private
def valid_address(sender: address) -> bool:
    selfdestruct(sender)
    return True
@public
def test():
    assert self.valid_address(msg.sender)
    """
    assert_compile_failed(lambda: get_contract(code), ConstancyViolationException)

    code = """
@public
def test():
    assert create_forwarder_to(self) == 1
    """
    assert_compile_failed(lambda: get_contract(code), ConstancyViolationException)

    foreign_code = """
state: uint256
@public
def not_really_constant() -> uint256:
    self.state += 1
    return self.state
    """
    code = """
contract ForeignContract:
    def not_really_constant() -> uint256: constant

@public
def test():
    assert ForeignContract(msg.sender).not_really_constant() == 1
    """
    c1 = get_contract(foreign_code)
    c2 = get_contract(code, *[c1.address])
    # static call prohibits state change
    assert_tx_failed(lambda: c2.test())
