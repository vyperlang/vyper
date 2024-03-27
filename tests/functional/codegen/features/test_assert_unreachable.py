import pytest


@pytest.fixture(scope="module")
def initial_balance():
    return 10**20


def test_unreachable_refund(revm_env, get_contract, tx_failed):
    code = """
@external
def foo():
    assert msg.sender != msg.sender, UNREACHABLE
    """

    c = get_contract(code)
    a0 = revm_env.deployer
    gas_sent = 10**6
    with tx_failed():
        c.foo(transact={"from": a0, "gas": gas_sent, "gasPrice": 10})

    result = revm_env.evm.result
    assert result.gas_used == gas_sent  # Drains all gains sent
    assert not result.is_success and result.is_halt


def test_basic_unreachable(revm_env, get_contract, tx_failed):
    code = """
@external
def foo(val: int128) -> bool:
    assert val > 0, UNREACHABLE
    assert val == 2, UNREACHABLE
    return True
    """

    c = get_contract(code)

    assert c.foo(2) is True

    with tx_failed(exc_text="InvalidFEOpcode"):
        c.foo(1)
    with tx_failed(exc_text="InvalidFEOpcode"):
        c.foo(-1)
    with tx_failed(exc_text="InvalidFEOpcode"):
        c.foo(-2)


def test_basic_call_unreachable(revm_env, get_contract, tx_failed):
    code = """

@view
@internal
def _test_me(val: int128) -> bool:
    return val == 33

@external
def foo(val: int128) -> int128:
    assert self._test_me(val), UNREACHABLE
    return -123
    """

    c = get_contract(code)

    assert c.foo(33) == -123

    with tx_failed(exc_text="InvalidFEOpcode"):
        c.foo(1)
    with tx_failed(exc_text="InvalidFEOpcode"):
        c.foo(-1)


def test_raise_unreachable(revm_env, get_contract, tx_failed):
    code = """
@external
def foo():
    raise UNREACHABLE
    """

    c = get_contract(code)

    with tx_failed(exc_text="InvalidFEOpcode"):
        c.foo()
