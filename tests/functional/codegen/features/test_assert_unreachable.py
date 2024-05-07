from tests.evm_backends.base_env import EvmError


def test_unreachable_refund(env, get_contract, tx_failed):
    code = """
@external
def foo():
    assert msg.sender != msg.sender, UNREACHABLE
    """
    env.set_balance(env.deployer, 10**20)

    c = get_contract(code)
    gas_sent = 10**6
    with tx_failed(EvmError, exc_text=env.invalid_opcode_error):
        c.foo(gas=gas_sent, gas_price=10)

    assert env.last_result.gas_used == gas_sent  # Drains all gas sent per INVALID opcode


def test_basic_unreachable(env, get_contract, tx_failed):
    code = """
@external
def foo(val: int128) -> bool:
    assert val > 0, UNREACHABLE
    assert val == 2, UNREACHABLE
    return True
    """

    c = get_contract(code)

    assert c.foo(2) is True

    with tx_failed(EvmError, exc_text=env.invalid_opcode_error):
        c.foo(1)
    with tx_failed(EvmError, exc_text=env.invalid_opcode_error):
        c.foo(-1)
    with tx_failed(EvmError, exc_text=env.invalid_opcode_error):
        c.foo(-2)


def test_basic_call_unreachable(env, get_contract, tx_failed):
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

    with tx_failed(EvmError, exc_text=env.invalid_opcode_error):
        c.foo(1)
    with tx_failed(EvmError, exc_text=env.invalid_opcode_error):
        c.foo(-1)


def test_raise_unreachable(env, get_contract, tx_failed):
    code = """
@external
def foo():
    raise UNREACHABLE
    """

    c = get_contract(code)

    with tx_failed(EvmError, exc_text=env.invalid_opcode_error):
        c.foo()
