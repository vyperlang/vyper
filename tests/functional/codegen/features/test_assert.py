import pytest


def test_assert_refund(env, get_contract, tx_failed):
    code = """
@external
def foo():
    raise
    """
    c = get_contract(code)
    env.set_balance(env.deployer, 10**7)
    gas_sent = 10**6
    with tx_failed():
        c.foo(gas=gas_sent, gas_price=10)

    # check we issued `revert`, which does not consume all gas
    assert env.last_result.gas_used < gas_sent


def test_assert_reason(env, get_contract, tx_failed):
    code = """
err: String[32]

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

@external
def test4(a: int128, reason_str: String[32]) -> int128:
    self.err = reason_str
    assert a > 1, self.err
    return 1 + a

@external
def test5(reason_str: String[32]):
    self.err = reason_str
    raise self.err
    """
    c = get_contract(code)

    assert c.test(2) == 3
    with tx_failed(exc_text="larger than one please"):
        c.test(0)

    # a = 0, b = 1
    with tx_failed(exc_text="a is not large enough"):
        c.test2(0, 1, "")

    # a = 1, b = 0
    with tx_failed(exc_text="b may only be 1 because I said so"):
        c.test2(2, 2, " because I said so")

    # return correct value
    assert c.test2(5, 1, "") == 17

    with tx_failed(exc_text="An exception"):
        c.test3("An exception")

    assert c.test4(2, "msg") == 3

    with tx_failed(exc_text="larger than one again please"):
        c.test4(0, "larger than one again please")

    with tx_failed(exc_text="A storage exception"):
        c.test5("A storage exception")


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


def test_assert_staticcall(get_contract, env, tx_failed):
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
def test(c: ForeignContract):
    assert staticcall c.not_really_constant() == 1
    """
    c1 = get_contract(foreign_code)
    c2 = get_contract(code)

    # static call prohibits state change
    with tx_failed():
        c2.test(c1.address)


def test_assert_in_for_loop(get_contract, tx_failed):
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


def test_assert_with_reason_in_for_loop(get_contract, tx_failed):
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


def test_assert_reason_revert_length(env, get_contract, tx_failed):
    code = """
@external
def test() -> int128:
    assert 1 == 2, "oops"
    return 1
"""
    c = get_contract(code)
    with tx_failed(exc_text="oops"):
        c.test()
