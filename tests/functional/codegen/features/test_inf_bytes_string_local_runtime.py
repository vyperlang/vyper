import hashlib
import json

import pytest

from tests.evm_backends.abi import abi_decode, abi_encode
from tests.evm_backends.base_env import EvmError, ExecutionReverted
from vyper.compiler import compile_code
from vyper.exceptions import StructureException
from vyper.utils import EIP_3860_LIMIT, keccak256, method_id


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


def _deploy_with_ctor_data(env, code, ctor_data, settings):
    out = compile_code(code, output_formats=["abi", "bytecode"], settings=settings)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x")) + ctor_data
    return env.deploy(out["abi"], initcode)


def _deploy_raw_returner(env, payload):
    assert len(payload) < 256
    runtime = bytes(
        [0x60, len(payload), 0x60, 12, 0x60, 0, 0x39, 0x60, len(payload), 0x60, 0, 0xF3]
    )
    runtime += payload
    initcode = bytes.fromhex(f"61{len(runtime):04x}3d81600a3d39f3") + runtime
    return env.deploy([], initcode)


def _call(env, contract, signature, args_schema=None, args=None):
    # raw call helper for tests which check the exact wire encoding of the
    # returndata (abi decoding would hide padding and tuple wrapping)
    calldata = method_id(signature)
    if args_schema is not None:
        calldata += abi_encode(args_schema, args)
    return env.message_call(contract.address, data=calldata)


def _revert_data(excinfo):
    revert_hex = excinfo.value.args[0]
    assert revert_hex.startswith("0x")
    return bytes.fromhex(revert_hex[2:])


def test_inf_bytes_local_from_bounded(get_contract):
    code = """
@external
def foo() -> Bytes[5]:
    x: Bytes[INF] = b"hello"
    return slice(x, 0, 5)
    """

    c = get_contract(code)
    assert c.foo() == b"hello"


def test_inf_string_local_from_bounded(get_contract):
    code = """
@external
def foo() -> String[5]:
    x: String[INF] = "hello"
    return slice(x, 0, 5)
    """

    c = get_contract(code)
    assert c.foo() == "hello"


def test_inf_bytes_and_string_locals_from_bounded_params(get_contract):
    code = """
@external
def foo(a: Bytes[5], b: String[5]) -> (Bytes[5], String[5]):
    x: Bytes[INF] = a
    y: String[INF] = b
    return slice(x, 0, 5), slice(y, 0, 5)
    """

    c = get_contract(code)
    assert c.foo(b"hello", "world") == (b"hello", "world")


def test_inf_bytes_and_string_external_return_from_bounded(get_contract):
    code = """
@external
def foo() -> Bytes[INF]:
    return b"hello"

@external
def bar() -> String[INF]:
    return "world"
    """

    c = get_contract(code)
    assert c.foo() == b"hello"
    assert c.bar() == "world"


def test_inf_bytes_external_return_from_local(get_contract):
    code = """
@external
def foo() -> Bytes[INF]:
    x: Bytes[INF] = b"hello"
    x = b"dynamic"
    return x
    """

    c = get_contract(code)
    assert c.foo() == b"dynamic"


def test_msg_data_as_inf_bytes_rvalue(get_contract):
    code = """
@external
def foo() -> Bytes[INF]:
    return msg.data
    """

    c = get_contract(code)
    assert c.foo() == method_id("foo()")


def test_runtime_length_slice_returns_inf_bytes(get_contract):
    code = """
@external
def from_local() -> Bytes[INF]:
    x: Bytes[INF] = b"hello"
    return slice(x, 0, len(x))

@external
def from_msg_data() -> Bytes[INF]:
    return slice(msg.data, 0, len(msg.data))
    """

    c = get_contract(code)
    assert c.from_local() == b"hello"
    expected = method_id("from_msg_data()")
    assert c.from_msg_data() == expected


def test_code_as_inf_bytes_rvalue(env, get_contract):
    code = """
@external
def self_code() -> Bytes[INF]:
    return self.code

@external
def addr_code(addr: address) -> Bytes[INF]:
    return addr.code
    """

    c = get_contract(code)
    expected = env.get_code(c.address)
    assert c.self_code() == expected
    assert c.addr_code(c.address) == expected


def test_inf_bytes_internal_forwarding(get_contract):
    code = """
@internal
def _bar() -> Bytes[INF]:
    x: Bytes[INF] = b"hello"
    return x

@external
def foo() -> Bytes[INF]:
    return self._bar()
    """

    c = get_contract(code)
    assert c.foo() == b"hello"


def test_inf_string_internal_nested_forwarding(get_contract):
    code = """
@internal
def _baz() -> String[INF]:
    x: String[INF] = "hello"
    return x

@internal
def _bar() -> String[INF]:
    return self._baz()

@external
def foo() -> String[INF]:
    return self._bar()
    """

    c = get_contract(code)
    assert c.foo() == "hello"


def test_empty_inf_bytes_internal_forwarding(get_contract):
    code = """
@internal
def _bar() -> Bytes[INF]:
    x: Bytes[INF] = b""
    return x

@external
def foo() -> Bytes[INF]:
    return self._bar()
    """

    c = get_contract(code)
    assert c.foo() == b""


def test_inf_bytes_internal_forwarding_no_inline(get_contract, no_inlining_settings):
    code = """
@internal
def _bar() -> Bytes[INF]:
    x: Bytes[INF] = b"hello"
    return x

@external
def foo() -> Bytes[INF]:
    return self._bar()
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.foo() == b"hello"


def test_inf_bytes_external_param_roundtrip(get_contract):
    code = """
@external
def echo(x: Bytes[INF]) -> Bytes[INF]:
    return x
    """

    c = get_contract(code)
    assert c.echo(b"unbounded input") == b"unbounded input"


def test_large_inf_bytes_external_param_roundtrip(get_contract):
    payload = bytes((i * 17) % 256 for i in range(2001))
    code = """
@external
def echo(x: Bytes[INF]) -> Bytes[INF]:
    return x
    """

    c = get_contract(code)
    assert c.echo(payload) == payload


def test_inf_string_external_param_roundtrip(get_contract):
    code = """
@external
def echo(x: String[INF]) -> String[INF]:
    return x
    """

    c = get_contract(code)
    assert c.echo("unbounded input") == "unbounded input"


def test_empty_inf_external_params(get_contract):
    code = """
@external
def sizes(x: Bytes[INF], y: String[INF]) -> (uint256, uint256):
    return len(x), len(y)
    """

    c = get_contract(code)
    assert c.sizes(b"", "") == (0, 0)


def test_inf_bytes_external_param_bounded_slice(get_contract):
    code = """
@external
def first_three(x: Bytes[INF]) -> Bytes[3]:
    return slice(x, 0, 3)
    """

    c = get_contract(code)
    assert c.first_three(b"abcdef") == b"abc"


def test_inf_bytes_external_kwarg_default_and_provided(get_contract):
    code = """
@external
def echo(x: Bytes[INF] = b"default") -> Bytes[INF]:
    return x
    """

    c = get_contract(code)
    assert c.echo() == b"default"

    assert c.echo(b"provided") == b"provided"


def test_inf_bytes_staticcall_return_roundtrip(get_contract):
    target_code = """
@external
@view
def data() -> Bytes[INF]:
    return b"external bytes"
    """

    caller_code = """
interface Source:
    def data() -> Bytes[INF]: view

@external
def get(addr: address) -> Bytes[INF]:
    return staticcall Source(addr).data()
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address) == b"external bytes"


def test_large_inf_bytes_staticcall_return(get_contract):
    payload = bytes((i * 31) % 256 for i in range(2001))
    target_code = """
@external
@view
def data(x: Bytes[2001]) -> Bytes[INF]:
    return x
    """

    caller_code = """
interface Source:
    def data(x: Bytes[2001]) -> Bytes[INF]: view

@external
def get(addr: address, x: Bytes[2001]) -> Bytes[INF]:
    return staticcall Source(addr).data(x)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, payload) == payload


def test_large_inf_bytes_staticcall_inf_arg_roundtrip(get_contract):
    payload = bytes((i * 29) % 256 for i in range(2001))
    target_code = """
@external
@view
def data(x: Bytes[INF]) -> Bytes[INF]:
    return x
    """

    caller_code = """
interface Source:
    def data(x: Bytes[INF]) -> Bytes[INF]: view

@external
def get(addr: address, x: Bytes[INF]) -> Bytes[INF]:
    return staticcall Source(addr).data(x)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, payload) == payload


def test_inf_bytes_staticcall_default_return_value(env, get_contract):
    payload = b"live returndata"
    caller_code = """
interface Source:
    def data() -> Bytes[INF]: view

@external
def get(addr: address) -> Bytes[INF]:
    return staticcall Source(addr).data(default_return_value=b"fallback")
    """

    caller = get_contract(caller_code)
    empty_target = _deploy_raw_returner(env, b"")
    assert caller.get(empty_target.address) == b"fallback"

    target = _deploy_raw_returner(env, abi_encode("(bytes)", (payload,)))
    assert caller.get(target.address) == payload


def test_inf_bytes_staticcall_default_return_value_from_inf_local(env, get_contract):
    payload = bytes((i * 37) % 256 for i in range(2001))
    caller_code = """
interface Source:
    def data() -> Bytes[INF]: view

@external
def get(addr: address, x: Bytes[INF]) -> Bytes[INF]:
    fallback: Bytes[INF] = x
    return staticcall Source(addr).data(default_return_value=fallback)
    """

    caller = get_contract(caller_code)
    empty_target = _deploy_raw_returner(env, b"")
    assert caller.get(empty_target.address, payload) == payload


def test_inf_bytes_staticcall_tuple_return_roundtrip(get_contract):
    payload = bytes((i * 41) % 256 for i in range(2001))
    target_code = """
@external
@view
def pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return 31, x
    """

    caller_code = """
interface Source:
    def pair(x: Bytes[INF]) -> (uint256, Bytes[INF]): view

@external
def get(addr: address, x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return staticcall Source(addr).pair(x)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, payload) == (31, payload)


def test_inf_bytes_staticcall_singleton_tuple_return(env, get_contract):
    payload = bytes((i * 43) % 256 for i in range(2001))

    def encode_singleton_bytes_tuple(value):
        padding = b"\x00" * (-len(value) % 32)
        return (
            (32).to_bytes(32, "big")
            + (32).to_bytes(32, "big")
            + len(value).to_bytes(32, "big")
            + value
            + padding
        )

    target_code = """
@external
@view
def one(x: Bytes[INF]) -> (Bytes[INF],):
    return (x,)
    """

    caller_code = """
interface Source:
    def one(x: Bytes[INF]) -> (Bytes[INF],): view

@external
def get(addr: address, x: Bytes[INF]) -> (Bytes[INF],):
    return staticcall Source(addr).one(x)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    ret = _call(env, caller, "get(address,bytes)", "(address,bytes)", (target.address, payload))
    assert ret == encode_singleton_bytes_tuple(payload)


def test_inf_bytes_staticcall_tuple_return_subscript(get_contract):
    target_code = """
@external
@view
def pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return 37, x
    """

    caller_code = """
interface Source:
    def pair(x: Bytes[INF]) -> (uint256, Bytes[INF]): view

@external
def get(addr: address, x: Bytes[INF]) -> Bytes[3]:
    return slice((staticcall Source(addr).pair(x))[1], 0, 3)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, b"catdog") == b"cat"


def test_inf_bytes_staticcall_tuple_default_return_value(env, get_contract):
    caller_code = """
interface Source:
    def pair() -> (uint256, Bytes[INF]): view

@external
def get(addr: address) -> (uint256, Bytes[INF]):
    return staticcall Source(addr).pair(default_return_value=(7, b"fallback"))
    """

    caller = get_contract(caller_code)
    empty_target = _deploy_raw_returner(env, b"")
    assert caller.get(empty_target.address) == (7, b"fallback")

    target = _deploy_raw_returner(env, abi_encode("(uint256,bytes)", (9, b"live")))
    assert caller.get(target.address) == (9, b"live")


def test_inf_bytes_staticcall_tuple_default_return_value_from_bounded_local(env, get_contract):
    caller_code = """
interface Source:
    def pair() -> (uint256, Bytes[INF]): view

@external
def get(addr: address) -> (uint256, Bytes[INF]):
    d: (uint256, Bytes[8]) = (7, b"fallback")
    return staticcall Source(addr).pair(default_return_value=d)
    """

    caller = get_contract(caller_code)
    empty_target = _deploy_raw_returner(env, b"")
    assert caller.get(empty_target.address) == (7, b"fallback")


def test_inf_bytes_extcall_tuple_return_roundtrip(get_contract):
    payload = bytes((i * 47) % 256 for i in range(2001))
    target_code = """
@external
def pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return 43, x
    """

    caller_code = """
interface Source:
    def pair(x: Bytes[INF]) -> (uint256, Bytes[INF]): nonpayable

@external
def get(addr: address, x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return extcall Source(addr).pair(x)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, payload) == (43, payload)


def test_inf_bytes_string_staticcall_tuple_multi_dynamic_return(get_contract):
    payload = bytes((i * 49) % 256 for i in range(2001))
    text = "external tuple " * 170 + "tail"
    target_code = """
@external
@view
def mix(x: Bytes[INF], y: String[INF]) -> (Bytes[INF], uint256, String[INF]):
    return x, 53, y
    """

    caller_code = """
interface Source:
    def mix(x: Bytes[INF], y: String[INF]) -> (Bytes[INF], uint256, String[INF]): view

@external
def get(addr: address, x: Bytes[INF], y: String[INF]) -> (Bytes[INF], uint256, String[INF]):
    return staticcall Source(addr).mix(x, y)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, payload, text) == (payload, 53, text)


def test_inf_bytes_staticcall_inf_arg_with_static_args(get_contract):
    code = """
@external
@view
def data(a: uint256, x: Bytes[INF], b: uint256) -> Bytes[3]:
    assert a == 11
    assert b == 22
    return slice(x, 0, 3)
    """

    caller_code = """
interface Source:
    def data(a: uint256, x: Bytes[INF], b: uint256) -> Bytes[3]: view

@external
def get(addr: address, x: Bytes[INF]) -> Bytes[3]:
    return staticcall Source(addr).data(11, x, 22)
    """

    target = get_contract(code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, b"abcdef") == b"abc"


def test_inf_bytes_staticcall_snapshots_primitive_arg_before_later_mutation(get_contract):
    target_code = """
@external
@view
def data(a: uint256, x: Bytes[INF], marker: uint256) -> uint256:
    return a * 100 + len(x) * 10 + marker
    """
    caller_code = """
interface Source:
    def data(a: uint256, x: Bytes[INF], marker: uint256) -> uint256: view

stored: uint256

@internal
def _mutate() -> uint256:
    self.stored = 2
    return 7

@external
def get(addr: address, x: Bytes[INF]) -> (uint256, uint256):
    self.stored = 6
    result: uint256 = staticcall Source(addr).data(self.stored, x, self._mutate())
    return result, self.stored
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, b"cat") == (637, 2)


def test_inf_bytes_internal_call_snapshots_primitive_arg_before_later_mutation(
    get_contract, no_inlining_settings
):
    code = """
stored: uint256

@internal
def _mutate() -> uint256:
    self.stored = 2
    return 7

@internal
def _data(a: uint256, x: Bytes[INF], marker: uint256) -> uint256:
    return a * 100 + len(x) * 10 + marker

@external
def get(x: Bytes[INF]) -> (uint256, uint256):
    self.stored = 6
    result: uint256 = self._data(self.stored, x, self._mutate())
    return result, self.stored
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.get(b"cat") == (637, 2)


def test_inf_bytes_staticcall_inf_arg_with_bounded_dynamic_args(get_contract):
    code = """
@external
@view
def data(prefix: Bytes[7], x: Bytes[INF], suffix: Bytes[9]) -> Bytes[INF]:
    assert prefix == b"prelude"
    assert suffix == b"tail"
    return x
    """

    caller_code = """
interface Source:
    def data(prefix: Bytes[7], x: Bytes[INF], suffix: Bytes[9]) -> Bytes[INF]: view

@external
def get(addr: address, prefix: Bytes[7], x: Bytes[INF], suffix: Bytes[9]) -> Bytes[INF]:
    return staticcall Source(addr).data(prefix, x, suffix)
    """

    target = get_contract(code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, b"prelude", b"kitten", b"tail") == b"kitten"


def test_inf_string_staticcall_return_roundtrip(get_contract):
    target_code = """
@external
@view
def data() -> String[INF]:
    return "external string"
    """

    caller_code = """
interface Source:
    def data() -> String[INF]: view

@external
def get(addr: address) -> String[INF]:
    return staticcall Source(addr).data()
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address) == "external string"


def test_inf_string_staticcall_inf_arg_roundtrip(get_contract):
    target_code = """
@external
@view
def data(x: String[INF]) -> String[INF]:
    return x
    """

    caller_code = """
interface Source:
    def data(x: String[INF]) -> String[INF]: view

@external
def get(addr: address, x: String[INF]) -> String[INF]:
    return staticcall Source(addr).data(x)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    payload = "external string argument " * 80 + "tail"
    assert caller.get(target.address, payload) == payload


def test_inf_bytes_staticcall_return_bounded_slice(get_contract):
    target_code = """
@external
@view
def data() -> Bytes[INF]:
    return b"external bytes"
    """

    caller_code = """
interface Source:
    def data() -> Bytes[INF]: view

@external
def get(addr: address) -> Bytes[8]:
    x: Bytes[INF] = staticcall Source(addr).data()
    return slice(x, 0, 8)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address) == b"external"


def test_empty_inf_bytes_staticcall_return(get_contract):
    target_code = """
@external
@view
def data() -> Bytes[INF]:
    return b""
    """

    caller_code = """
interface Source:
    def data() -> Bytes[INF]: view

@external
def get(addr: address) -> Bytes[INF]:
    return staticcall Source(addr).data()
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address) == b""


def test_inf_bytes_staticcall_return_rejects_malformed_abi(env, get_contract, tx_failed):
    caller_code = """
interface Source:
    def data() -> Bytes[INF]: view

@external
def get(addr: address) -> Bytes[INF]:
    return staticcall Source(addr).data()
    """

    caller = get_contract(caller_code)

    def word(value):
        return value.to_bytes(32, "big")

    # Legacy accepts this non-canonical but in-bounds offset as an empty bytes
    # return; the INF path matches that leniency.
    target = _deploy_raw_returner(env, word(0))
    assert caller.get(target.address) == b""

    malformed_payloads = [word(2**256 - 31), word(32), word(32) + word(33) + b"\x01" * 32]

    for payload in malformed_payloads:
        target = _deploy_raw_returner(env, payload)
        with tx_failed():
            caller.get(target.address)


def test_inf_bytes_staticcall_tuple_return_bounds_bounded_dynamic_member(
    env, get_contract, tx_failed
):
    caller_code = """
interface Source:
    def pair() -> (Bytes[4], Bytes[INF]): view

@external
def get(addr: address) -> (Bytes[4], Bytes[INF]):
    return staticcall Source(addr).pair()
    """

    def word(value):
        return value.to_bytes(32, "big")

    caller = get_contract(caller_code)
    payload = word(2**251) + word(64) + word(0)
    target = _deploy_raw_returner(env, payload)

    with tx_failed():
        caller.get(target.address)


def test_inf_bytes_abi_decode_allows_missing_padding(get_contract, tx_failed):
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF], unwrap_tuple=False)
    """

    c = get_contract(code)

    def word(value):
        return value.to_bytes(32, "big")

    assert c.dec(word(31) + b"\x01" * 31) == b"\x01" * 31

    with tx_failed():
        c.dec(word(31) + b"\x01" * 30)


def test_inf_bytes_extcall_return_roundtrip(get_contract):
    target_code = """
@external
def data() -> Bytes[INF]:
    return b"mutable bytes"
    """

    caller_code = """
interface Source:
    def data() -> Bytes[INF]: nonpayable

@external
def get(addr: address) -> Bytes[INF]:
    return extcall Source(addr).data()
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address) == b"mutable bytes"


def test_inf_bytes_extcall_inf_arg_roundtrip(get_contract):
    target_code = """
@external
def data(x: Bytes[INF]) -> Bytes[INF]:
    return x
    """

    caller_code = """
interface Source:
    def data(x: Bytes[INF]) -> Bytes[INF]: nonpayable

@external
def get(addr: address, x: Bytes[INF]) -> Bytes[INF]:
    return extcall Source(addr).data(x)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, b"mutable") == b"mutable"


def test_inf_bytes_json_abi_staticcall_return(get_contract, make_input_bundle):
    target_code = """
@external
@view
def data() -> Bytes[INF]:
    return b"json abi bytes"
    """

    target = get_contract(target_code)

    caller_code = """
import source as Source

@external
def get(addr: address) -> Bytes[INF]:
    return staticcall Source(addr).data()
    """

    source_abi = [
        {
            "type": "function",
            "name": "data",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"name": "", "type": "bytes"}],
        }
    ]
    input_bundle = make_input_bundle({"source.json": json.dumps(source_abi)})
    caller = get_contract(caller_code, input_bundle=input_bundle)
    assert caller.get(target.address) == b"json abi bytes"


def test_inf_bytes_json_abi_external_call_freezes_bounded_arg_in_runtime_encoding(
    get_contract, make_input_bundle
):
    target_code = """
@external
@view
def lengths(a: Bytes[8], b: Bytes[INF], marker: uint256) -> uint256:
    return len(a) * 100 + len(b) * 10 + marker
    """
    caller_code = """
import source as Source

a: Bytes[8]

@internal
def _mutate() -> uint256:
    self.a = b"xy"
    return 7

@external
def check(addr: address, b: Bytes[INF]) -> (uint256, Bytes[8]):
    self.a = b"abcdef"
    r: uint256 = staticcall Source(addr).lengths(self.a, b, self._mutate())
    return r, self.a
    """
    source_abi = [
        {
            "type": "function",
            "name": "lengths",
            "stateMutability": "view",
            "inputs": [
                {"name": "a", "type": "bytes"},
                {"name": "b", "type": "bytes"},
                {"name": "marker", "type": "uint256"},
            ],
            "outputs": [{"name": "", "type": "uint256"}],
        }
    ]

    target = get_contract(target_code)
    input_bundle = make_input_bundle({"source.json": json.dumps(source_abi)})
    caller = get_contract(caller_code, input_bundle=input_bundle)
    assert caller.check(target.address, b"cat") == (637, b"xy")


def test_inf_string_json_abi_staticcall_return(get_contract, make_input_bundle):
    target_code = """
@external
@view
def data() -> String[INF]:
    return "json abi string"
    """

    target = get_contract(target_code)

    caller_code = """
import source as Source

@external
def get(addr: address) -> String[INF]:
    return staticcall Source(addr).data()
    """

    source_abi = [
        {
            "type": "function",
            "name": "data",
            "stateMutability": "view",
            "inputs": [],
            "outputs": [{"name": "", "type": "string"}],
        }
    ]
    input_bundle = make_input_bundle({"source.json": json.dumps(source_abi)})
    caller = get_contract(caller_code, input_bundle=input_bundle)
    assert caller.get(target.address) == "json abi string"


def test_inf_bytes_abi_encode_default_tuple(get_contract):
    payload = bytes((i * 19) % 256 for i in range(2001))
    code = """
@external
def enc(x: Bytes[INF]) -> Bytes[INF]:
    return abi_encode(x)
    """

    c = get_contract(code)
    assert c.enc(payload) == abi_encode("(bytes)", (payload,))


def test_inf_bytes_abi_encode_no_tuple(get_contract):
    payload = bytes((i * 23) % 256 for i in range(2001))
    code = """
@external
def enc(x: Bytes[INF]) -> Bytes[INF]:
    return abi_encode(x, ensure_tuple=False)
    """

    c = get_contract(code)
    assert c.enc(payload) == abi_encode("bytes", payload)


def test_inf_bytes_abi_encode_method_id_and_static_args(get_contract):
    payload = b"abcdef"
    code = """
@external
def enc(x: Bytes[INF]) -> Bytes[INF]:
    a: uint256 = 11
    b: uint256 = 22
    return abi_encode(a, x, b, method_id=method_id("foo(uint256,bytes,uint256)"))
    """

    c = get_contract(code)
    expected = method_id("foo(uint256,bytes,uint256)")
    expected += abi_encode("(uint256,bytes,uint256)", (11, payload, 22))
    assert c.enc(payload) == expected


def test_inf_bytes_abi_encode_method_id_bounded_dynarray_below_bound(env, get_contract):
    # the allocation size uses the DynArray bound while the actual encoding
    # uses the runtime length, so the encoded length is smaller than the
    # allocation estimate; the result must still be an exact encoding with
    # clean tail padding after the 4-byte method_id prefix.
    payload = b"\xff" * 300
    code = """
@internal
def _dirty(x: Bytes[INF]) -> uint256:
    y: Bytes[INF] = abi_encode(x, x)
    return len(y)

@external
def enc(x: Bytes[INF], d: DynArray[uint256, 4]) -> Bytes[INF]:
    assert self._dirty(x) > 0
    return abi_encode(x, d, method_id=0xa1b2c3d4)
    """

    c = get_contract(code)
    ret = _call(env, c, "enc(bytes,uint256[])", "(bytes,uint256[])", (payload, [7]))
    expected = b"\xa1\xb2\xc3\xd4" + abi_encode("(bytes,uint256[])", (payload, [7]))
    assert ret == abi_encode("(bytes)", (expected,))


def test_inf_string_abi_encode_default_tuple(get_contract):
    payload = "abi string " * 170 + "tail"
    code = """
@external
def enc(x: String[INF]) -> Bytes[INF]:
    return abi_encode(x)
    """

    c = get_contract(code)
    assert c.enc(payload) == abi_encode("(string)", (payload,))


def test_inf_bytes_abi_decode_default_tuple(get_contract):
    payload = bytes((i * 37) % 256 for i in range(2001))
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF])
    """

    c = get_contract(code)
    encoded = abi_encode("(bytes)", (payload,))
    assert c.dec(encoded) == payload

    assert c.dec((0).to_bytes(32, "big")) == b""


def test_inf_bytes_abi_decode_no_tuple(get_contract):
    payload = bytes((i * 41) % 256 for i in range(2001))
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF], unwrap_tuple=False)
    """

    c = get_contract(code)
    encoded = abi_encode("bytes", payload)
    assert c.dec(encoded) == payload


def test_bounded_bytes_abi_decode_short_payload_zeroes_return_padding(env, get_contract):
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[100]:
    return abi_decode(x, Bytes[100], unwrap_tuple=False)
    """

    c = get_contract(code)

    def word(value):
        return value.to_bytes(32, "big")

    encoded = word(3) + b"abc" + b"\xff" * 29
    ret = _call(env, c, "dec(bytes)", "(bytes)", (encoded,))
    assert ret == word(32) + word(3) + b"abc" + b"\x00" * 29


def test_bounded_dynarray_abi_decode_bounds_dynamic_element_head(get_contract, tx_failed):
    code = """
@external
def dec(x: Bytes[INF]) -> DynArray[Bytes[4], 2]:
    return abi_decode(x, DynArray[Bytes[4], 2], unwrap_tuple=False)
    """

    c = get_contract(code)

    def word(value):
        return value.to_bytes(32, "big")

    payload = word(1) + word(2**251)
    # bounded element types keep the legacy failure model: an absurd element
    # head offset fails on memory expansion rather than an explicit bounds
    # revert, so accept any EVM failure here
    with tx_failed(EvmError):
        c.dec(payload)


def test_inf_bytes_abi_decode_rejects_malformed_payload(get_contract, tx_failed):
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF])

@external
def dec_no_tuple(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF], unwrap_tuple=False)
    """

    c = get_contract(code)

    def word(value):
        return value.to_bytes(32, "big")

    for payload in [word(32), word(32) + word(2) + b"a"]:
        with tx_failed():
            c.dec(payload)

    for payload in [b"", word(2) + b"a"]:
        with tx_failed():
            c.dec_no_tuple(payload)


def test_inf_string_abi_decode_default_tuple(get_contract):
    payload = "decoded string " * 150 + "tail"
    code = """
@external
def dec(x: Bytes[INF]) -> String[INF]:
    return abi_decode(x, String[INF])
    """

    c = get_contract(code)
    encoded = abi_encode("(string)", (payload,))
    assert c.dec(encoded) == payload


def test_inf_bytes_abi_encode_decode_local_roundtrip(get_contract):
    payload = bytes((i * 43) % 256 for i in range(2001))
    code = """
@external
def roundtrip(x: Bytes[INF]) -> Bytes[INF]:
    encoded: Bytes[INF] = abi_encode(x)
    return abi_decode(encoded, Bytes[INF])
    """

    c = get_contract(code)
    assert c.roundtrip(payload) == payload


def test_inf_bytes_concat_runtime_length(get_contract):
    payload = bytes((i * 79) % 256 for i in range(2001))
    code = """
@external
def join(x: Bytes[INF]) -> Bytes[INF]:
    return concat(b"pre:", x, b":post")
    """

    c = get_contract(code)
    assert c.join(payload) == b"pre:" + payload + b":post"


def test_inf_string_concat_runtime_length(get_contract):
    payload = "concat string " * 170 + "tail"
    code = """
@external
def join(x: String[INF]) -> String[INF]:
    return concat("pre:", x, ":post")
    """

    c = get_contract(code)
    assert c.join(payload) == "pre:" + payload + ":post"


def test_inf_bytes_concat_trailing_bytesm_word_boundary(get_contract):
    # lengths are chosen so each trailing bytesM word-store lands in the last
    # data word of its exact-sized output (31+1 and 28+4 both fill a word);
    # the next buffer is allocated immediately above, so a store escaping the
    # first allocation corrupts it
    payload_a = bytes((i * 83) % 256 for i in range(31))
    payload_b = bytes((i * 89) % 256 for i in range(28))
    code = """
@external
def join(x: Bytes[INF], y: Bytes[INF]) -> Bytes[INF]:
    t: bytes1 = 0xde
    a: Bytes[INF] = concat(x, t)
    b: Bytes[INF] = concat(y, 0xdeadbeef)
    return concat(a, b)
    """

    c = get_contract(code)
    expected = payload_a + b"\xde" + payload_b + b"\xde\xad\xbe\xef"
    assert c.join(payload_a, payload_b) == expected


def test_inf_bytes_string_keccak256_runtime_length(get_contract, keccak):
    payload = bytes((i * 81) % 256 for i in range(2001))
    text = "hash string " * 170 + "tail"
    code = """
@external
def hash_bytes(x: Bytes[INF]) -> bytes32:
    return keccak256(x)

@external
def hash_string(x: String[INF]) -> bytes32:
    return keccak256(x)
    """

    c = get_contract(code)
    assert c.hash_bytes(payload) == keccak(payload)
    assert c.hash_string(text) == keccak(text.encode())


def test_inf_string_uint2str(get_contract):
    code = """
@external
def direct(x: uint256) -> String[INF]:
    return uint2str(x)

@external
def local(x: uint256) -> String[INF]:
    y: String[INF] = uint2str(x)
    return y
    """

    c = get_contract(code)
    assert c.direct(2**256 - 1) == str(2**256 - 1)
    assert c.local(0) == "0"


def test_inf_bytes_string_cross_convert(get_contract, tx_failed):
    code = """
@external
def to_bytes(x: String[10]) -> Bytes[INF]:
    return convert(x, Bytes[INF])

@external
def to_string(x: Bytes[10]) -> String[INF]:
    y: String[INF] = convert(x, String[INF])
    return y

@external
def inf_string_to_inf_bytes(x: String[INF]) -> Bytes[INF]:
    return convert(x, Bytes[INF])

@external
def inf_bytes_to_inf_string(x: Bytes[INF]) -> String[INF]:
    return convert(x, String[INF])

@external
def bytes_to_bounded(x: Bytes[INF]) -> Bytes[5]:
    return convert(x, Bytes[5])

@external
def string_to_bounded(x: String[INF]) -> String[5]:
    return convert(x, String[5])

@external
def bytes_to_string_bounded(x: Bytes[INF]) -> String[5]:
    return convert(x, String[5])

@external
def string_to_bytes_bounded(x: String[INF]) -> Bytes[5]:
    return convert(x, Bytes[5])
    """

    c = get_contract(code)
    assert c.to_bytes("hello") == b"hello"
    assert c.to_string(b"world") == "world"
    assert c.inf_string_to_inf_bytes("hello") == b"hello"
    assert c.inf_bytes_to_inf_string(b"world") == "world"
    assert c.bytes_to_bounded(b"abcde") == b"abcde"
    assert c.string_to_bounded("abcde") == "abcde"
    assert c.bytes_to_string_bounded(b"abcde") == "abcde"
    assert c.string_to_bytes_bounded("abcde") == b"abcde"

    with tx_failed():
        c.bytes_to_bounded(b"abcdef")
    with tx_failed():
        c.string_to_bounded("abcdef")


def test_inf_bytes_to_primitive_convert(get_contract, tx_failed):
    code = """
@external
def to_uint256(x: Bytes[INF]) -> uint256:
    return convert(x, uint256)

@external
def to_uint8(x: Bytes[INF]) -> uint8:
    return convert(x, uint8)

@external
def to_bytes4(x: Bytes[INF]) -> bytes4:
    return convert(x, bytes4)

@external
def to_bool(x: Bytes[INF]) -> bool:
    return convert(x, bool)
    """

    c = get_contract(code)
    assert c.to_uint256((123).to_bytes(32, "big")) == 123
    assert c.to_uint8(b"\x7b") == 123
    assert c.to_bytes4(b"abcd") == b"abcd"
    assert c.to_bool(b"\x00\x01") is True

    with tx_failed():
        c.to_uint256(b"\x01" * 33)
    with tx_failed():
        c.to_uint8(b"\x01\x00")
    with tx_failed():
        c.to_bytes4(b"abcde")


def test_empty_inf_bytes_signed_convert(get_contract):
    # empty INF bytestrings allocate only the length word; the data word
    # position may hold garbage from previously reclaimed scratch memory.
    # sar of that garbage must not leak into the conversion result.
    code = """
@internal
def _dirty_scratch(a: Bytes[INF]) -> bytes32:
    t: Bytes[INF] = concat(a, a)
    return keccak256(t)

@external
def to_int256(a: Bytes[INF], n: uint256) -> int256:
    h: bytes32 = self._dirty_scratch(a)
    x: Bytes[INF] = slice(a, 0, n)
    return convert(x, int256)

@external
def to_decimal(a: Bytes[INF], n: uint256) -> decimal:
    h: bytes32 = self._dirty_scratch(a)
    x: Bytes[INF] = slice(a, 0, n)
    return convert(x, decimal)
    """

    c = get_contract(code)
    # dirty scratch memory with 0xff words, then convert an empty slice
    dirt = b"\xff" * 32
    assert c.to_int256(dirt, 0) == 0
    assert c.to_decimal(dirt, 0) == 0


def test_inf_bytes_string_print(get_contract):
    payload = bytes((i * 63) % 256 for i in range(2001))
    text = "print string " * 170 + "tail"
    code = """
@external
def log_values(x: Bytes[INF], y: String[INF]) -> (uint256, uint256, bytes32, bytes32):
    print(x, y)
    print(x, hardhat_compat=True)
    print(y, hardhat_compat=True)
    return len(x), len(y), sha256(x), sha256(y)
    """

    c = get_contract(code)
    assert c.log_values(payload, text) == (
        len(payload),
        len(text),
        hashlib.sha256(payload).digest(),
        hashlib.sha256(text.encode()).digest(),
    )


def test_inf_bytes_string_misc_builtins(get_contract, tx_failed):
    code = """
@external
def hash_values(x: Bytes[INF], y: String[INF]) -> (bytes32, bytes32):
    return sha256(x), sha256(y)

@external
def word_at(x: Bytes[INF], start: uint256) -> bytes32:
    return extract32(x, start)

@external
def compare(x: Bytes[INF], y: Bytes[INF], a: String[INF], b: String[INF]) -> (bool, bool):
    return x == y, a != b

@external
def boom(x: Bytes[INF]):
    raw_revert(x)
    """

    c = get_contract(code)
    payload = bytes((i * 17) % 256 for i in range(80))
    text = "sha string " * 20 + "tail"

    assert c.hash_values(payload, text) == (
        hashlib.sha256(payload).digest(),
        hashlib.sha256(text.encode()).digest(),
    )

    assert c.word_at(payload, 7) == payload[7:39]

    assert c.compare(payload, payload, "cat", "kitten") == (True, True)

    revert_data = method_id("NoFives()") + b"\x01\x02"
    with tx_failed(exc_text=revert_data.hex()):
        c.boom(revert_data)


def test_inf_bytes_raw_call_direct_return(get_contract):
    payload = bytes((i * 47) % 256 for i in range(2001))
    code = """
IDENTITY: constant(address) = 0x0000000000000000000000000000000000000004

@external
def echo(x: Bytes[INF]) -> Bytes[INF]:
    return raw_call(IDENTITY, x, max_outsize=4096)
    """

    c = get_contract(code)
    assert c.echo(payload) == payload


def test_inf_bytes_raw_call_checkable_tuple_unpack(get_contract):
    payload = bytes((i * 53) % 256 for i in range(2001))
    code = """
IDENTITY: constant(address) = 0x0000000000000000000000000000000000000004

@external
def echo(x: Bytes[INF]) -> Bytes[INF]:
    ok: bool = False
    y: Bytes[INF] = b""
    ok, y = raw_call(IDENTITY, x, max_outsize=4096, revert_on_failure=False)
    assert ok
    return y
    """

    c = get_contract(code)
    assert c.echo(payload) == payload


def test_inf_bytes_raw_call_checkable_direct_tuple_return(get_contract):
    payload = bytes((i * 59) % 256 for i in range(2001))
    code = """
IDENTITY: constant(address) = 0x0000000000000000000000000000000000000004

@external
def echo(x: Bytes[INF]) -> (bool, Bytes[INF]):
    return raw_call(IDENTITY, x, max_outsize=4096, revert_on_failure=False)
    """

    c = get_contract(code)
    assert c.echo(payload) == (True, payload)


def test_inf_bytes_raw_return(env, get_contract):
    payload = bytes((i * 61) % 256 for i in range(2001))
    code = """
@external
@raw_return
def echo(x: Bytes[INF]) -> Bytes[INF]:
    return x

@external
@raw_return
def literal() -> Bytes[INF]:
    return b"literal"

@external
@raw_return
def empty() -> Bytes[INF]:
    return b""
    """

    c = get_contract(code)
    assert _call(env, c, "echo(bytes)", "(bytes)", (payload,)) == payload
    assert _call(env, c, "literal()") == b"literal"
    assert _call(env, c, "empty()") == b""


def test_inf_bytes_tuple_literal_return(get_contract):
    payload = bytes((i * 73) % 256 for i in range(2001))
    code = """
@external
def pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    y: Bytes[INF] = x
    return 7, y
    """

    c = get_contract(code)
    assert c.pair(payload) == (7, payload)


def test_inf_string_tuple_literal_return(get_contract):
    payload = "tuple string " * 170 + "tail"
    code = """
@external
def pair(x: String[INF]) -> (uint256, String[INF]):
    y: String[INF] = x
    return 9, y
    """

    c = get_contract(code)
    assert c.pair(payload) == (9, payload)


def test_inf_bytes_tuple_empty_literal_return(get_contract):
    code = """
@external
def pair() -> (uint256, Bytes[INF]):
    return 1, b""
    """

    c = get_contract(code)
    assert c.pair() == (1, b"")


def test_inf_bytes_tuple_ternary_return(get_contract):
    code = """
@external
def choose(flag: bool) -> (uint256, Bytes[INF]):
    a: uint256 = 1
    b: uint256 = 2
    x: Bytes[INF] = b"cat"
    y: Bytes[INF] = b"kitten"
    return (a, x) if flag else (b, y)
    """

    c = get_contract(code)
    assert c.choose(True) == (1, b"cat")
    assert c.choose(False) == (2, b"kitten")


def test_inf_bytes_tuple_ternary_materializes_bounded_arm(get_contract):
    code = """
@external
def choose(flag: bool, x: Bytes[INF]) -> (uint256, Bytes[INF]):
    d: (uint256, Bytes[4]) = (9, b"fish")
    n: uint256 = 7
    return d if flag else (n, x)
    """

    c = get_contract(code)
    assert c.choose(True, b"cat") == (9, b"fish")
    assert c.choose(False, b"kitten") == (7, b"kitten")


def test_inf_bytes_singleton_tuple_literal_return(env, get_contract):
    payload = bytes((i * 83) % 256 for i in range(2001))

    def encode_singleton_bytes_tuple(value):
        padding = b"\x00" * (-len(value) % 32)
        return (
            (32).to_bytes(32, "big")
            + (32).to_bytes(32, "big")
            + len(value).to_bytes(32, "big")
            + value
            + padding
        )

    code = """
@external
def from_arg(x: Bytes[INF]) -> (Bytes[INF],):
    return (x,)

@external
def empty() -> (Bytes[INF],):
    return (b"",)
    """

    c = get_contract(code)
    ret = _call(env, c, "from_arg(bytes)", "(bytes)", (payload,))
    assert ret == encode_singleton_bytes_tuple(payload)
    assert _call(env, c, "empty()") == encode_singleton_bytes_tuple(b"")


def test_inf_bytes_internal_tuple_return(get_contract, no_inlining_settings):
    payload = bytes((i * 89) % 256 for i in range(2001))
    code = """
@internal
def _pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return 11, x

@external
def pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return self._pair(x)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.pair(payload) == (11, payload)


def test_inf_bytes_internal_tuple_return_with_bounded_complex_member(
    get_contract, no_inlining_settings
):
    payload = bytes((i * 90) % 256 for i in range(2001))
    code = """
@internal
def _pair(x: Bytes[INF]) -> (Bytes[5], Bytes[INF]):
    return b"small", x

@external
def pair(x: Bytes[INF]) -> (Bytes[5], Bytes[INF]):
    return self._pair(x)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.pair(payload) == (b"small", payload)


def test_inf_bytes_internal_tuple_return_with_bounded_complex_member_after_inf(
    get_contract, no_inlining_settings
):
    payload = bytes((i * 97) % 256 for i in range(2001))
    code = """
@internal
def _pair(x: Bytes[INF]) -> (Bytes[INF], Bytes[5]):
    return x, b"small"

@external
def pair(x: Bytes[INF]) -> (Bytes[INF], Bytes[5]):
    return self._pair(x)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.pair(payload) == (payload, b"small")


def test_inf_bytes_internal_tuple_return_subscript(get_contract, no_inlining_settings):
    code = """
@internal
def _pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return 17, x

@external
def second(x: Bytes[INF]) -> Bytes[3]:
    return slice(self._pair(x)[1], 0, 3)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.second(b"cat") == b"cat"


def test_inf_string_internal_tuple_return_subscript(get_contract, no_inlining_settings):
    code = """
@internal
def _pair(x: String[INF]) -> (uint256, String[INF]):
    return 17, x

@external
def second(x: String[INF]) -> String[6]:
    return slice(self._pair(x)[1], 0, 6)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.second("kitten") == "kitten"


def test_inf_bytes_string_internal_tuple_return_mixed_ordering(get_contract, no_inlining_settings):
    payload = bytes((i * 91) % 256 for i in range(2001))
    text = "mixed ordering " * 150 + "tail"
    code = """
@internal
def _mix(x: Bytes[INF], y: String[INF]) -> (Bytes[INF], uint256, String[INF]):
    return x, 23, y

@external
def mix(x: Bytes[INF], y: String[INF]) -> (Bytes[INF], uint256, String[INF]):
    return self._mix(x, y)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.mix(payload, text) == (payload, 23, text)


def test_inf_bytes_internal_tuple_return_swapped_dynamic_sources(
    get_contract, no_inlining_settings
):
    code = """
@internal
def _swap(x: Bytes[INF], y: Bytes[INF]) -> (Bytes[INF], Bytes[INF]):
    return y, x

@external
def swap(x: Bytes[INF], y: Bytes[INF]) -> (Bytes[INF], Bytes[INF]):
    return self._swap(x, y)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.swap(b"first", b"second value") == (b"second value", b"first")


def test_inf_bytes_internal_tuple_return_many_ordinary_members(get_contract, no_inlining_settings):
    payload = bytes((i * 95) % 256 for i in range(2001))
    code = """
@internal
def _many(x: Bytes[INF]) -> (uint256, uint256, uint256, Bytes[INF]):
    return 1, 2, 3, x

@external
def many(x: Bytes[INF]) -> (uint256, uint256, uint256, Bytes[INF]):
    return self._many(x)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.many(payload) == (1, 2, 3, payload)


def test_inf_bytes_internal_singleton_tuple_return(env, get_contract, no_inlining_settings):
    payload = bytes((i * 92) % 256 for i in range(2001))

    def encode_singleton_bytes_tuple(value):
        padding = b"\x00" * (-len(value) % 32)
        return (
            (32).to_bytes(32, "big")
            + (32).to_bytes(32, "big")
            + len(value).to_bytes(32, "big")
            + value
            + padding
        )

    code = """
@internal
def _one(x: Bytes[INF]) -> (Bytes[INF],):
    return (x,)

@external
def one(x: Bytes[INF]) -> (Bytes[INF],):
    return self._one(x)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    ret = _call(env, c, "one(bytes)", "(bytes)", (payload,))
    assert ret == encode_singleton_bytes_tuple(payload)


def test_inf_bytes_internal_tuple_return_forwarding(get_contract, no_inlining_settings):
    payload = bytes((i * 93) % 256 for i in range(2001))
    code = """
@internal
def _pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return 19, x

@internal
def _forward(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return self._pair(x)

@external
def pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return self._forward(x)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.pair(payload) == (19, payload)


def test_inf_bytes_internal_tuple_unpack(get_contract, no_inlining_settings):
    code = """
@internal
def _pair() -> (uint256, Bytes[INF]):
    return 13, b"kitten"

@external
def unpack() -> (uint256, Bytes[6]):
    a: uint256 = 0
    b: Bytes[INF] = b""
    a, b = self._pair()
    return a, slice(b, 0, 6)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.unpack() == (13, b"kitten")


def test_inf_bytes_string_internal_tuple_multi_dynamic_return(get_contract, no_inlining_settings):
    payload = bytes((i * 97) % 256 for i in range(2001))
    text = "venom tuple " * 180 + "tail"
    code = """
@internal
def _pair(x: Bytes[INF], y: String[INF]) -> (Bytes[INF], String[INF]):
    return x, y

@external
def pair(x: Bytes[INF], y: String[INF]) -> (Bytes[INF], String[INF]):
    return self._pair(x, y)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.pair(payload, text) == (payload, text)


def test_inf_bytes_raw_create_bytecode_param(env, get_contract):
    to_deploy_code = """
foo: public(uint256)
    """
    out = compile_code(to_deploy_code, output_formats=["bytecode", "bytecode_runtime"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))
    runtime = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))

    deployer_code = """
@external
def deploy(s: Bytes[INF]) -> address:
    return raw_create(s)
    """

    deployer = get_contract(deployer_code)
    addr = deployer.deploy(initcode)
    assert env.get_code(addr) == runtime


def test_inf_bytes_raw_create_oversized_initcode_no_revert(get_contract):
    deployer_code = """
@external
def deploy(s: Bytes[INF]) -> address:
    return raw_create(s, revert_on_failure=False)
    """

    deployer = get_contract(deployer_code)
    initcode = b"\x00" * (EIP_3860_LIMIT + 1)
    assert deployer.deploy(initcode) == "0x0000000000000000000000000000000000000000"


def test_inf_bytes_raw_create_oversized_initcode_reverts(get_contract, tx_failed):
    deployer_code = """
@external
def deploy(s: Bytes[INF]) -> address:
    return raw_create(s)
    """

    deployer = get_contract(deployer_code)
    initcode = b"\x00" * (EIP_3860_LIMIT + 1)
    with tx_failed():
        deployer.deploy(initcode)


def test_inf_bytes_raw_create_bytecode_local_with_ctor_arg(env, get_contract):
    to_deploy_code = """
foo: public(uint256)

@deploy
def __init__(x: uint256):
    self.foo = x
    """
    out = compile_code(to_deploy_code, output_formats=["bytecode", "bytecode_runtime"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))
    runtime = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))

    deployer_code = """
@external
def deploy(s: Bytes[INF], x: uint256) -> address:
    bytecode: Bytes[INF] = s
    return raw_create(bytecode, x)
    """

    deployer = get_contract(deployer_code)
    addr = deployer.deploy(initcode, 42)
    assert env.get_code(addr) == runtime
    ret = env.message_call(addr, data=method_id("foo()"))
    assert abi_decode("(uint256)", ret) == (42,)


def test_inf_bytes_raw_create_unbounded_ctor_arg(env, get_contract, compiler_settings):
    payload = bytes((i * 73) % 256 for i in range(2001))
    to_deploy_code = """
stored: Bytes[2001]

@deploy
def __init__(x: Bytes[INF]):
    self.stored = slice(x, 0, 2001)

@external
def get() -> Bytes[2001]:
    return self.stored
    """
    out = compile_code(to_deploy_code, output_formats=["bytecode"], settings=compiler_settings)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    deployer_code = """
@external
def deploy(s: Bytes[INF], x: Bytes[INF]) -> address:
    return raw_create(s, x)
    """

    deployer = get_contract(deployer_code)
    addr = deployer.deploy(initcode, payload)
    ret = env.message_call(addr, data=method_id("get()"))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_bytes_raw_create_snapshots_primitive_ctor_arg_before_later_mutation(
    env, get_contract, compiler_settings
):
    child_code = """
stored: public(uint256)
marker: public(uint256)

@deploy
def __init__(a: uint256, x: Bytes[INF], marker: uint256):
    self.stored = a * 100 + len(x) * 10
    self.marker = marker
    """
    out = compile_code(child_code, output_formats=["bytecode"], settings=compiler_settings)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    deployer_code = """
stored: uint256

@internal
def _mutate() -> uint256:
    self.stored = 2
    return 7

@external
def deploy(s: Bytes[INF], x: Bytes[INF]) -> address:
    self.stored = 6
    return raw_create(s, self.stored, x, self._mutate())
    """

    deployer = get_contract(deployer_code)
    addr = deployer.deploy(initcode, b"cat")

    ret = env.message_call(addr, data=method_id("stored()"))
    assert abi_decode("(uint256)", ret) == (630,)
    ret = env.message_call(addr, data=method_id("marker()"))
    assert abi_decode("(uint256)", ret) == (7,)


def test_inf_bytes_create_from_blueprint_unbounded_ctor_arg(
    env, get_contract, deploy_blueprint_for
):
    payload = bytes((i * 79) % 256 for i in range(2001))
    to_deploy_code = """
stored: Bytes[2001]

@deploy
def __init__(x: Bytes[INF]):
    self.stored = slice(x, 0, 2001)

@external
def get() -> Bytes[2001]:
    return self.stored
    """
    blueprint, _ = deploy_blueprint_for(to_deploy_code)

    code = """
@external
def deploy(target: address, x: Bytes[INF]) -> address:
    return create_from_blueprint(target, x)
    """

    deployer = get_contract(code)
    addr = deployer.deploy(blueprint.address, payload)
    ret = env.message_call(addr, data=method_id("get()"))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_bytes_create_from_blueprint_raw_args_unbounded(
    env, get_contract, deploy_blueprint_for
):
    payload = bytes((i * 83) % 256 for i in range(2001))
    to_deploy_code = """
stored: Bytes[2001]

@deploy
def __init__(x: Bytes[INF]):
    self.stored = slice(x, 0, 2001)

@external
def get() -> Bytes[2001]:
    return self.stored
    """
    blueprint, _ = deploy_blueprint_for(to_deploy_code)
    raw_args = abi_encode("(bytes)", (payload,))

    code = """
@external
def deploy(target: address, args: Bytes[INF]) -> address:
    return create_from_blueprint(target, args, raw_args=True)
    """

    deployer = get_contract(code)
    addr = deployer.deploy(blueprint.address, raw_args)
    ret = env.message_call(addr, data=method_id("get()"))
    assert abi_decode("(bytes)", ret) == (payload,)


_BLUEPRINT_INF_CTOR_CODE = """
@deploy
def __init__(x: Bytes[INF]):
    pass
    """


def test_inf_bytes_create_from_blueprint_oversized_initcode_no_revert(
    get_contract, deploy_blueprint_for
):
    blueprint, _ = deploy_blueprint_for(_BLUEPRINT_INF_CTOR_CODE)

    code = """
@external
def deploy(target: address, x: Bytes[INF]) -> address:
    return create_from_blueprint(target, x, revert_on_failure=False)
    """

    deployer = get_contract(code)
    payload = b"\x00" * (EIP_3860_LIMIT + 1)
    assert deployer.deploy(blueprint.address, payload) == "0x" + "00" * 20


def test_inf_bytes_create_from_blueprint_oversized_initcode_reverts(
    get_contract, deploy_blueprint_for, tx_failed
):
    blueprint, _ = deploy_blueprint_for(_BLUEPRINT_INF_CTOR_CODE)

    code = """
@external
def deploy(target: address, x: Bytes[INF]) -> address:
    return create_from_blueprint(target, x)
    """

    deployer = get_contract(code)
    payload = b"\x00" * (EIP_3860_LIMIT + 1)
    with tx_failed():
        deployer.deploy(blueprint.address, payload)


def test_inf_bytes_create_from_blueprint_raw_args_oversized_initcode_no_revert(
    get_contract, deploy_blueprint_for
):
    blueprint, _ = deploy_blueprint_for(_BLUEPRINT_INF_CTOR_CODE)

    code = """
@external
def deploy(target: address, args: Bytes[INF]) -> address:
    return create_from_blueprint(target, args, raw_args=True, revert_on_failure=False)
    """

    deployer = get_contract(code)
    raw_args = b"\x00" * (EIP_3860_LIMIT + 1)
    assert deployer.deploy(blueprint.address, raw_args) == "0x" + "00" * 20


def test_inf_bytes_create_from_blueprint_raw_args_oversized_initcode_reverts(
    get_contract, deploy_blueprint_for, tx_failed
):
    blueprint, _ = deploy_blueprint_for(_BLUEPRINT_INF_CTOR_CODE)

    code = """
@external
def deploy(target: address, args: Bytes[INF]) -> address:
    return create_from_blueprint(target, args, raw_args=True)
    """

    deployer = get_contract(code)
    raw_args = b"\x00" * (EIP_3860_LIMIT + 1)
    with tx_failed():
        deployer.deploy(blueprint.address, raw_args)


def test_inf_string_raw_create_unbounded_ctor_arg(env, get_contract, compiler_settings):
    payload = "raw create string " * 120 + "tail"
    to_deploy_code = """
stored_len: public(uint256)
stored_hash: public(bytes32)

@deploy
def __init__(x: String[INF]):
    self.stored_len = len(x)
    self.stored_hash = sha256(x)
    """
    out = compile_code(to_deploy_code, output_formats=["bytecode"], settings=compiler_settings)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    deployer_code = """
@external
def deploy(s: Bytes[INF], x: String[INF]) -> address:
    return raw_create(s, x)
    """

    deployer = get_contract(deployer_code)
    addr = deployer.deploy(initcode, payload)
    ret = env.message_call(addr, data=method_id("stored_len()"))
    assert abi_decode("(uint256)", ret) == (len(payload),)
    ret = env.message_call(addr, data=method_id("stored_hash()"))
    assert abi_decode("(bytes32)", ret) == (hashlib.sha256(payload.encode()).digest(),)


def test_inf_string_create_from_blueprint_unbounded_ctor_arg(
    env, get_contract, deploy_blueprint_for
):
    payload = "blueprint string " * 130 + "tail"
    to_deploy_code = """
stored_len: public(uint256)
stored_hash: public(bytes32)

@deploy
def __init__(x: String[INF]):
    self.stored_len = len(x)
    self.stored_hash = sha256(x)
    """
    blueprint, _ = deploy_blueprint_for(to_deploy_code)

    code = """
@external
def deploy(target: address, x: String[INF]) -> address:
    return create_from_blueprint(target, x)
    """

    deployer = get_contract(code)
    addr = deployer.deploy(blueprint.address, payload)
    ret = env.message_call(addr, data=method_id("stored_len()"))
    assert abi_decode("(uint256)", ret) == (len(payload),)
    ret = env.message_call(addr, data=method_id("stored_hash()"))
    assert abi_decode("(bytes32)", ret) == (hashlib.sha256(payload.encode()).digest(),)


@pytest.mark.parametrize("call", ["raw_create(s, (x, y))", "create_from_blueprint(target, (x, y))"])
def test_create_rejects_nested_inf_ctor_arg(call, compiler_settings):
    target_arg = "target: address, " if call.startswith("create_from_blueprint") else ""
    code = f"""
@external
def deploy({target_arg}s: Bytes[INF], x: Bytes[INF], y: uint256) -> address:
    return {call}
    """

    with pytest.raises(StructureException) as e:
        compile_code(code, settings=compiler_settings)
    message = "constructor arguments cannot contain nested unbounded sequence types"
    assert e.value.message == message


def test_inf_bytes_raw_log_data(env, get_contract):
    payload = bytes((i * 61) % 256 for i in range(2001))
    code = """
@external
def emit_raw(x: Bytes[INF]):
    raw_log([], x)
    """

    c = get_contract(code)
    c.emit_raw(payload)
    assert env.get_logs(c, raw=True)[0][1] == payload


_EVENT_PAYLOADS = [b"", b"abc", bytes(range(33)), bytes((i * 67) % 256 for i in range(2001))]


@pytest.mark.parametrize("payload", _EVENT_PAYLOADS)
def test_inf_bytes_event_data(env, get_contract, payload):
    code = """
event E:
    x: Bytes[INF]

@external
def emit_event(x: Bytes[INF]):
    log E(x=x)
    """

    c = get_contract(code)
    c.emit_event(payload)
    assert env.get_logs(c, raw=True)[0][1] == abi_encode("(bytes)", (payload,))


def test_inf_bytes_event_data_from_bounded_arg(env, get_contract):
    code = """
event E:
    x: Bytes[INF]

@external
def emit_event():
    log E(x=b"abc")
    """

    c = get_contract(code)
    c.emit_event()
    assert env.get_logs(c, raw=True)[0][1] == abi_encode("(bytes)", (b"abc",))


def test_inf_string_event_data(env, get_contract):
    payload = "event string " * 170 + "tail"
    code = """
event E:
    x: String[INF]

@external
def emit_event(x: String[INF]):
    log E(x=x)
    """

    c = get_contract(code)
    c.emit_event(payload)
    assert env.get_logs(c, raw=True)[0][1] == abi_encode("(string)", (payload,))


def test_inf_string_event_data_with_static_args(env, get_contract):
    payload = "event string " * 170 + "tail"
    code = """
event E:
    a: uint256
    x: String[INF]
    b: uint256

@external
def emit_event(x: String[INF]):
    log E(a=11, x=x, b=22)
    """

    c = get_contract(code)
    c.emit_event(payload)
    assert env.get_logs(c, raw=True)[0][1] == abi_encode(
        "(uint256,string,uint256)", (11, payload, 22)
    )


def test_inf_bytes_event_data_with_bounded_dynamic_args(env, get_contract):
    payload = bytes((i * 71) % 256 for i in range(2001))
    code = """
event E:
    x: Bytes[INF]
    ys: DynArray[uint256, 3]
    s: String[8]

@external
def emit_event(x: Bytes[INF]):
    log E(x=x, ys=[1, 2, 3], s="tail")
    """

    c = get_contract(code)
    c.emit_event(payload)
    assert env.get_logs(c, raw=True)[0][1] == abi_encode(
        "(bytes,uint256[],string)", (payload, [1, 2, 3], "tail")
    )


@pytest.mark.parametrize("xs", [[], [7], list(range(100))])
def test_inf_dynarray_event_data(env, get_contract, xs):
    code = """
event E:
    xs: DynArray[uint256, INF]

@external
def emit_event(xs: DynArray[uint256, INF]):
    log E(xs=xs)
    """

    c = get_contract(code)
    c.emit_event(xs)
    assert env.get_logs(c, raw=True)[0][1] == abi_encode("(uint256[])", (xs,))


def test_inf_dynarray_event_snapshots_arg_before_later_mutation(env, get_contract):
    code = """
event E:
    xs: DynArray[uint256, INF]
    popped: uint256

@external
def emit_event():
    x: DynArray[uint256, INF] = [1, 2, 3]
    log E(xs=x, popped=x.pop())
    """

    c = get_contract(code)
    c.emit_event()
    assert env.get_logs(c, raw=True)[0][1] == abi_encode("(uint256[],uint256)", ([1, 2, 3], 3))


@pytest.mark.parametrize("payload", _EVENT_PAYLOADS)
def test_indexed_inf_bytes_event_topic(env, get_contract, payload):
    code = """
event E:
    x: indexed(Bytes[INF])

@external
def emit_event(x: Bytes[INF]):
    log E(x=x)
    """

    c = get_contract(code)
    c.emit_event(payload)
    topics, data = env.get_logs(c, raw=True)[0]
    assert topics[1] == keccak256(payload)
    assert data == b""


def test_indexed_inf_string_event_topic(env, get_contract):
    payload = "indexed string " * 170 + "tail"
    code = """
event E:
    x: indexed(String[INF])

@external
def emit_event(x: String[INF]):
    log E(x=x)
    """

    c = get_contract(code)
    c.emit_event(payload)
    topics, data = env.get_logs(c, raw=True)[0]
    assert topics[1] == keccak256(payload.encode())
    assert data == b""


@pytest.mark.parametrize("payload", _EVENT_PAYLOADS)
def test_inf_bytes_custom_error_payload(get_contract, payload):
    code = """
error Oops:
    x: Bytes[INF]

@external
def boom(x: Bytes[INF]):
    raise Oops(x)
    """

    c = get_contract(code)
    with pytest.raises(ExecutionReverted) as excinfo:
        c.boom(payload)
    assert _revert_data(excinfo) == method_id("Oops(bytes)") + abi_encode("(bytes)", (payload,))


def test_inf_string_custom_error_payload_with_static_args(get_contract):
    payload = "error string " * 170 + "tail"
    code = """
error Oops:
    a: uint256
    x: String[INF]
    b: uint256

@external
def boom(x: String[INF]):
    assert len(x) == 0, Oops(a=11, x=x, b=22)
    """

    c = get_contract(code)
    with pytest.raises(ExecutionReverted) as excinfo:
        c.boom(payload)
    data = _revert_data(excinfo)
    assert data[:4] == method_id("Oops(uint256,string,uint256)")
    assert abi_decode("(uint256,string,uint256)", data[4:]) == (11, payload, 22)


@pytest.mark.parametrize("xs", [[], [7], list(range(100))])
def test_inf_dynarray_custom_error_payload(get_contract, xs):
    code = """
error Oops:
    xs: DynArray[uint256, INF]

@external
def boom(xs: DynArray[uint256, INF]):
    raise Oops(xs)
    """

    c = get_contract(code)
    with pytest.raises(ExecutionReverted) as excinfo:
        c.boom(xs)
    assert _revert_data(excinfo) == method_id("Oops(uint256[])") + abi_encode("(uint256[])", (xs,))


def test_inf_dynarray_custom_error_snapshots_arg_before_later_mutation(get_contract):
    code = """
error Oops:
    xs: DynArray[uint256, INF]
    popped: uint256

@external
def boom():
    x: DynArray[uint256, INF] = [1, 2, 3]
    raise Oops(x, x.pop())
    """

    c = get_contract(code)
    with pytest.raises(ExecutionReverted) as excinfo:
        c.boom()
    data = _revert_data(excinfo)
    assert data[:4] == method_id("Oops(uint256[],uint256)")
    assert abi_decode("(uint256[],uint256)", data[4:]) == ([1, 2, 3], 3)


def test_inf_bytes_constructor_arg(get_contract):
    payload = bytes((i * 7) % 256 for i in range(2001))
    code = """
saved: Bytes[2001]

@deploy
def __init__(a: Bytes[INF]):
    self.saved = slice(a, 0, 2001)

@external
def get() -> Bytes[2001]:
    return self.saved
    """

    c = get_contract(code, payload)
    assert c.get() == payload


def test_inf_bytes_constructor_arg_allows_truncated_data(env, compiler_settings):
    code = """
@deploy
def __init__(a: Bytes[INF]):
    pass

@external
def ok() -> uint256:
    return 1
    """

    def word(value):
        return value.to_bytes(32, "big")

    c = _deploy_with_ctor_data(env, code, word(32) + word(2001), compiler_settings)
    assert c.ok() == 1


def test_inf_bytes_external_param_rejects_truncated_calldata(env, get_contract, tx_failed):
    code = """
@external
def length(x: Bytes[INF]) -> uint256:
    return len(x)
    """

    c = get_contract(code)

    def word(value):
        return value.to_bytes(32, "big")

    calldata = method_id("length(bytes)") + word(32) + word(2001)
    with tx_failed():
        env.message_call(c.address, data=calldata)

    calldata = method_id("length(bytes)") + word(0)
    assert abi_decode("(uint256)", env.message_call(c.address, data=calldata)) == (0,)


def test_inf_bytes_external_param_allows_missing_padding(env, get_contract):
    code = """
@external
def length(x: Bytes[INF]) -> uint256:
    return len(x)
    """

    c = get_contract(code)

    def word(value):
        return value.to_bytes(32, "big")

    calldata = method_id("length(bytes)") + word(32) + word(3) + b"cat"
    assert abi_decode("(uint256)", env.message_call(c.address, data=calldata)) == (3,)


def test_inf_bytes_internal_arg_roundtrip(get_contract):
    payload = bytes((i * 13) % 256 for i in range(2001))
    code = """
@internal
def _echo(x: Bytes[INF]) -> Bytes[INF]:
    return x

@external
def echo(x: Bytes[INF]) -> Bytes[INF]:
    return self._echo(x)
    """

    c = get_contract(code)
    assert c.echo(payload) == payload


def test_inf_bytes_internal_arg_is_copied(get_contract):
    code = """
@internal
def _copy(x: Bytes[INF]) -> Bytes[INF]:
    return x

@external
def check() -> Bytes[3]:
    x: Bytes[INF] = b"abc"
    y: Bytes[INF] = self._copy(x)
    x = b"def"
    return slice(y, 0, 3)
    """

    c = get_contract(code)
    assert c.check() == b"abc"


def test_inf_bytes_internal_arg_reassignment_does_not_mutate_caller(get_contract):
    code = """
@internal
def _replace(x: Bytes[INF]) -> Bytes[3]:
    x = b"def"
    return slice(x, 0, 3)

@external
def check() -> (Bytes[3], Bytes[3]):
    x: Bytes[INF] = b"abc"
    y: Bytes[3] = self._replace(x)
    return y, slice(x, 0, 3)
    """

    c = get_contract(code)
    assert c.check() == (b"def", b"abc")


def test_empty_inf_bytes_and_string_locals(get_contract):
    code = """
@external
def foo() -> (uint256, uint256):
    x: Bytes[INF] = b""
    y: String[INF] = ""
    return len(x), len(y)
    """

    c = get_contract(code)
    assert c.foo() == (0, 0)


def test_empty_inf_bytes_and_string_builtin(get_contract):
    code = """
@external
def foo() -> Bytes[INF]:
    return empty(Bytes[INF])

@external
def bar() -> String[INF]:
    return empty(String[INF])
    """

    c = get_contract(code)
    assert c.foo() == b""
    assert c.bar() == ""


def test_empty_inf_bytes_dynamic_tuple_builtin(get_contract):
    code = """
@external
def value() -> (uint256, Bytes[INF]):
    return empty((uint256, Bytes[INF]))
    """

    c = get_contract(code)
    assert c.value() == (0, b"")


def test_empty_inf_string_dynamic_tuple_builtin(get_contract):
    code = """
@external
def value() -> (uint256, String[INF]):
    return empty((uint256, String[INF]))
    """

    c = get_contract(code)
    assert c.value() == (0, "")


def test_empty_nested_inf_aggregate_rejected(compiler_settings):
    code = """
@external
def value() -> uint256:
    return len(empty(((Bytes[INF],), uint256))[0][0])
    """

    with pytest.raises(StructureException) as e:
        compile_code(code, settings=compiler_settings)
    message = "empty() does not support unbounded sequence types inside aggregate types"
    assert e.value.message == message


def test_inf_bytes_local_reassignment_larger_and_smaller(get_contract):
    code = """
@external
def grow() -> Bytes[6]:
    x: Bytes[INF] = b"cat"
    x = b"kitten"
    return slice(x, 0, 6)

@external
def shrink() -> Bytes[3]:
    x: Bytes[INF] = b"kitten"
    x = b"cat"
    return slice(x, 0, 3)
    """

    c = get_contract(code)
    assert c.grow() == b"kitten"
    assert c.shrink() == b"cat"


def test_inf_bytes_local_reassignment_in_if(get_contract):
    code = """
@external
def foo(flag: bool) -> Bytes[3]:
    x: Bytes[INF] = b"abc"
    if flag:
        x = b"defg"
    return slice(x, 0, 3)
    """

    c = get_contract(code)
    assert c.foo(False) == b"abc"
    assert c.foo(True) == b"def"


def test_inf_bytes_local_reassignment_in_loop(get_contract):
    code = """
@external
def foo(flag: bool) -> Bytes[3]:
    x: Bytes[INF] = b"one"
    for i: uint256 in range(2):
        if flag and i == 1:
            x = b"two"
    return slice(x, 0, 3)
    """

    c = get_contract(code)
    assert c.foo(False) == b"one"
    assert c.foo(True) == b"two"
