"""
raw_call with an unbounded return (`max_outsize=INF`): the whole returndata
is captured as a Bytes[INF] value sized by the actual returndatasize.
"""

import pytest

from tests.evm_backends.abi import abi_encode
from tests.evm_backends.base_env import ExecutionReverted
from vyper.utils import method_id


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


def _deploy_runtime(env, runtime):
    initcode = bytes.fromhex(f"61{len(runtime):04x}3d81600a3d39f3") + runtime
    return env.deploy([], initcode)


def _deploy_echo(env):
    # CALLDATASIZE PUSH1 0 PUSH1 0 CALLDATACOPY CALLDATASIZE PUSH1 0 RETURN:
    # returns its calldata, so the caller picks the returndata
    return _deploy_runtime(env, bytes.fromhex("366000600037366000f3"))


def _deploy_reverting_echo(env):
    # as the echo, but REVERT
    return _deploy_runtime(env, bytes.fromhex("366000600037366000fd"))


def _deploy_tail_echo(env):
    # PUSH1 64 CALLDATASIZE SUB DUP1 PUSH1 64 PUSH1 0 CALLDATACOPY PUSH1 0 RETURN:
    # returns its calldata from byte 64 on
    return _deploy_runtime(env, bytes.fromhex("604036038060406000376000f3"))


def _call(env, contract, signature, args_schema, args):
    # raw call for tests which check the exact wire encoding of the
    # returndata (abi decoding would hide padding)
    calldata = method_id(signature) + abi_encode(args_schema, args)
    return env.message_call(contract.address, data=calldata)


def _revert_data(excinfo):
    revert_hex = excinfo.value.args[0]
    assert revert_hex.startswith("0x")
    return bytes.fromhex(revert_hex[2:])


_LARGE_PAYLOAD = bytes((i * 7) % 256 for i in range(10_000))

_CALL_KINDS = {
    "call": ("@nonpayable", ""),
    "delegatecall": ("@nonpayable", ", is_delegate_call=True"),
    "staticcall": ("@view", ", is_static_call=True"),
}


def test_empty_returndata(env, get_contract):
    code = """
@external
def foo(target: address) -> Bytes[INF]:
    return raw_call(target, b"", max_outsize=INF)
    """
    echo = _deploy_echo(env)
    c = get_contract(code)
    assert c.foo(echo.address) == b""
    assert _call(env, c, "foo(address)", "(address)", (echo.address,)) == abi_encode(
        "(bytes)", (b"",)
    )


@pytest.mark.parametrize("call_kind", _CALL_KINDS.keys())
def test_large_returndata(env, get_contract, call_kind):
    decorator, call_kwargs = _CALL_KINDS[call_kind]
    code = f"""
@external
{decorator}
def foo(target: address, data: Bytes[INF]) -> Bytes[INF]:
    return raw_call(target, data, max_outsize=INF{call_kwargs})
    """
    echo = _deploy_echo(env)
    c = get_contract(code)
    assert c.foo(echo.address, _LARGE_PAYLOAD) == _LARGE_PAYLOAD


def test_local_assignment(env, get_contract):
    code = """
@external
def foo(target: address, data: Bytes[INF]) -> Bytes[INF]:
    x: Bytes[INF] = raw_call(target, data, max_outsize=INF)
    assert len(x) == len(data)
    return x
    """
    echo = _deploy_echo(env)
    c = get_contract(code)
    assert c.foo(echo.address, b"hello world") == b"hello world"
    assert c.foo(echo.address, _LARGE_PAYLOAD) == _LARGE_PAYLOAD


def test_internal_forwarding(env, get_contract, no_inlining_settings):
    code = """
@internal
def _fetch(target: address, data: Bytes[INF]) -> Bytes[INF]:
    return raw_call(target, data, max_outsize=INF)

@internal
def _length(x: Bytes[INF]) -> uint256:
    return len(x)

@external
def fetch(target: address, data: Bytes[INF]) -> Bytes[INF]:
    return self._fetch(target, data)

@external
def length(target: address, data: Bytes[INF]) -> uint256:
    return self._length(raw_call(target, data, max_outsize=INF))
    """
    echo = _deploy_echo(env)
    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.fetch(echo.address, _LARGE_PAYLOAD) == _LARGE_PAYLOAD
    assert c.length(echo.address, _LARGE_PAYLOAD) == len(_LARGE_PAYLOAD)


def test_external_call_argument(env, get_contract):
    sink_code = """
@external
def consume(x: Bytes[INF]) -> Bytes[INF]:
    return x
    """
    code = """
interface Sink:
    def consume(x: Bytes[INF]) -> Bytes[INF]: nonpayable

@external
def foo(target: address, sink: address, data: Bytes[INF]) -> Bytes[INF]:
    return extcall Sink(sink).consume(raw_call(target, data, max_outsize=INF))
    """
    echo = _deploy_echo(env)
    sink = get_contract(sink_code)
    c = get_contract(code)
    assert c.foo(echo.address, sink.address, _LARGE_PAYLOAD) == _LARGE_PAYLOAD


def test_revert_propagates_returndata(env, get_contract):
    code = """
@external
def foo(target: address, data: Bytes[INF]) -> Bytes[INF]:
    return raw_call(target, data, max_outsize=INF)
    """
    reverter = _deploy_reverting_echo(env)
    c = get_contract(code)
    with pytest.raises(ExecutionReverted) as excinfo:
        c.foo(reverter.address, _LARGE_PAYLOAD)
    assert _revert_data(excinfo) == _LARGE_PAYLOAD


def test_msg_data_forwarding_proxy(env, get_contract):
    code = """
@external
def fwd(target: address, data: Bytes[INF]) -> Bytes[INF]:
    return raw_call(target, msg.data, max_outsize=INF)
    """
    echo = _deploy_echo(env)
    c = get_contract(code)
    calldata = method_id("fwd(address,bytes)") + abi_encode(
        "(address,bytes)", (echo.address, _LARGE_PAYLOAD)
    )
    assert env.message_call(c.address, data=calldata) == abi_encode("(bytes)", (calldata,))


def test_returndata_shorter_than_forwarded_calldata(env, get_contract):
    code = """
@external
def fwd(target: address, data: Bytes[INF]) -> Bytes[INF]:
    return raw_call(target, msg.data, max_outsize=INF)
    """
    tail_echo = _deploy_tail_echo(env)
    c = get_contract(code)
    calldata = method_id("fwd(address,bytes)") + abi_encode(
        "(address,bytes)", (tail_echo.address, b"\xff" * 256)
    )
    assert env.message_call(c.address, data=calldata) == abi_encode("(bytes)", (calldata[64:],))


@pytest.mark.parametrize("call_kind", _CALL_KINDS.keys())
def test_success_flag_and_returndata(env, get_contract, call_kind):
    decorator, call_kwargs = _CALL_KINDS[call_kind]
    code = f"""
@external
{decorator}
def foo(target: address, data: Bytes[INF]) -> (bool, Bytes[INF]):
    ok: bool = False
    res: Bytes[INF] = b""
    ok, res = raw_call(target, data, max_outsize=INF, revert_on_failure=False{call_kwargs})
    return ok, res
    """
    echo = _deploy_echo(env)
    reverter = _deploy_reverting_echo(env)
    c = get_contract(code)
    assert c.foo(echo.address, _LARGE_PAYLOAD) == (True, _LARGE_PAYLOAD)
    assert c.foo(echo.address, b"") == (True, b"")
    # the revert data comes back as the bytes member instead of raising
    assert c.foo(reverter.address, _LARGE_PAYLOAD) == (False, _LARGE_PAYLOAD)
    assert c.foo(reverter.address, b"") == (False, b"")


def test_success_flag_tuple_return(env, get_contract):
    code = """
@external
def foo(target: address, data: Bytes[INF]) -> (bool, Bytes[INF]):
    return raw_call(target, data, max_outsize=INF, revert_on_failure=False)
    """
    echo = _deploy_echo(env)
    reverter = _deploy_reverting_echo(env)
    c = get_contract(code)
    payload = b"\xff" * 33
    assert _call(env, c, "foo(address,bytes)", "(address,bytes)", (echo.address, payload)) == (
        abi_encode("(bool,bytes)", (True, payload))
    )
    assert _call(
        env, c, "foo(address,bytes)", "(address,bytes)", (reverter.address, payload)
    ) == abi_encode("(bool,bytes)", (False, payload))


def test_bounded_outsize_returned_as_unbounded_bytes(env, get_contract):
    code = """
@external
def foo(target: address, data: Bytes[INF]) -> Bytes[INF]:
    return raw_call(target, data, max_outsize=32)
    """
    echo = _deploy_echo(env)
    c = get_contract(code)
    payload = bytes(range(100))
    assert c.foo(echo.address, payload) == payload[:32]


def test_bounded_outsize_success_flag_returned_as_unbounded_bytes(env, get_contract):
    code = """
@external
def foo(target: address, data: Bytes[INF]) -> (bool, Bytes[INF]):
    return raw_call(target, data, max_outsize=32, revert_on_failure=False)
    """
    echo = _deploy_echo(env)
    c = get_contract(code)
    payload = bytes(range(100))
    assert c.foo(echo.address, payload) == (True, payload[:32])
