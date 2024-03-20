import pytest
from eth_tester.exceptions import TransactionFailed


# web3 returns f"execution reverted: {err_str}"
# TODO move exception string parsing logic into tx_failed
def _fixup_err_str(s):
    return s.replace("execution reverted: ", "")


def test_assert_refund(w3, get_contract_with_gas_estimation, tx_failed):
    code = """
@external
def foo():
    raise
    """
    c = get_contract_with_gas_estimation(code)
    a0 = w3.eth.accounts[0]
    gas_sent = 10**6
    tx_hash = c.foo(transact={"from": a0, "gas": gas_sent, "gasPrice": 10})
    # More info on receipt status:
    # https://github.com/ethereum/EIPs/blob/master/EIPS/eip-658.md#specification.
    tx_receipt = w3.eth.get_transaction_receipt(tx_hash)
    assert tx_receipt["status"] == 0
    # Checks for gas refund from revert
    assert tx_receipt["gasUsed"] < gas_sent


def test_assert_reason(w3, get_contract_with_gas_estimation, tx_failed, memory_mocker):
    code = """
@external
def test(a: int128) -> int128:
    assert a > 1, "larger than one please"
    return 1 + a

@external
def test2(a: int128, b: int128, extra_reason: String[32]) -> int128:
    c: int128 = 11
    assert a > 1, "a is not large enough"
    assert b == 1, concat("b may only be 1", extra_reason)
    return a + b + c

@external
def test3(reason_str: String[32]):
    raise reason_str
    """
    c = get_contract_with_gas_estimation(code)

    assert c.test(2) == 3
    with pytest.raises(TransactionFailed) as e_info:
        c.test(0)

    assert _fixup_err_str(e_info.value.args[0]) == "larger than one please"
    # a = 0, b = 1
    with pytest.raises(TransactionFailed) as e_info:
        c.test2(0, 1, "")
    assert _fixup_err_str(e_info.value.args[0]) == "a is not large enough"
    # a = 1, b = 0
    with pytest.raises(TransactionFailed) as e_info:
        c.test2(2, 2, " because I said so")
    assert _fixup_err_str(e_info.value.args[0]) == "b may only be 1" + " because I said so"
    # return correct value
    assert c.test2(5, 1, "") == 17

    with pytest.raises(TransactionFailed) as e_info:
        c.test3("An exception")
    assert _fixup_err_str(e_info.value.args[0]) == "An exception"


invalid_code = [
    """
@external
def test(a: int128) -> int128:
    assert a > 1, ""
    return 1 + a
    """,
    """
@external
def test(a: int128) -> int128:
    raise ""
    """,
    """
@external
def test():
    assert create_minimal_proxy_to(self)
    """,
]


@pytest.mark.parametrize("code", invalid_code)
def test_invalid_assertions(get_contract, assert_compile_failed, code):
    assert_compile_failed(lambda: get_contract(code))


valid_code = [
    """
@external
def mint(_to: address, _value: uint256):
    raise
    """,
    """
@internal
def ret1() -> int128:
    return 1
@external
def test():
    assert self.ret1() == 1
    """,
    """
@external
def test():
    assert raw_call(msg.sender, b'', max_outsize=1, gas=10, value=1000*1000) == b''
    """,
    """
@external
def test():
    assert create_minimal_proxy_to(self) == self
    """,
]


@pytest.mark.parametrize("code", valid_code)
def test_valid_assertions(get_contract, code):
    get_contract(code)


def test_assert_staticcall(get_contract, tx_failed, memory_mocker):
    foreign_code = """
state: uint256
@external
def not_really_constant() -> uint256:
    self.state += 1
    return self.state
    """
    code = """
interface ForeignContract:
    def not_really_constant() -> uint256: view

@external
def test():
    assert staticcall ForeignContract(msg.sender).not_really_constant() == 1
    """
    c1 = get_contract(foreign_code)
    c2 = get_contract(code, *[c1.address])
    # static call prohibits state change
    with tx_failed():
        c2.test()


def test_assert_in_for_loop(get_contract, tx_failed, memory_mocker):
    code = """
@external
def test(x: uint256[3]) -> bool:
    for i: uint256 in range(3):
        assert x[i] < 5
    return True
    """

    c = get_contract(code)

    c.test([1, 2, 3])
    with tx_failed():
        c.test([5, 1, 3])
    with tx_failed():
        c.test([1, 5, 3])
    with tx_failed():
        c.test([1, 3, 5])


def test_assert_with_reason_in_for_loop(get_contract, tx_failed, memory_mocker):
    code = """
@external
def test(x: uint256[3]) -> bool:
    for i: uint256 in range(3):
        assert x[i] < 5, "because reasons"
    return True
    """

    c = get_contract(code)

    c.test([1, 2, 3])
    with tx_failed():
        c.test([5, 1, 3])
    with tx_failed():
        c.test([1, 5, 3])
    with tx_failed():
        c.test([1, 3, 5])


def test_assert_reason_revert_length(w3, get_contract, tx_failed, memory_mocker):
    code = """
@external
def test() -> int128:
    assert 1 == 2, "oops"
    return 1
"""
    c = get_contract(code)
    with tx_failed(exc_text="oops"):
        c.test()
