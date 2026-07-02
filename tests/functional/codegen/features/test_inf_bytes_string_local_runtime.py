import hashlib
import json

import pytest

from tests.evm_backends.abi import abi_decode, abi_encode
from vyper.compiler import compile_code
from vyper.compiler.settings import Settings, VenomOptimizationFlags
from vyper.exceptions import StructureException
from vyper.utils import EIP_3860_LIMIT, method_id


def _venom_settings(*, disable_inlining=False):
    settings = Settings(experimental_codegen=True)
    if disable_inlining:
        settings.venom_flags = VenomOptimizationFlags(disable_inlining=True)
    return settings


def _compile_venom(code, output_formats, *, settings=None, input_bundle=None):
    return compile_code(
        code,
        output_formats=output_formats,
        settings=settings or _venom_settings(),
        input_bundle=input_bundle,
    )


def _deploy_venom(env, code, *, settings=None, input_bundle=None):
    out = _compile_venom(code, ["bytecode"], settings=settings, input_bundle=input_bundle)
    return env.deploy([], bytes.fromhex(out["bytecode"].removeprefix("0x")))


def _deploy_raw_returner(env, payload):
    assert len(payload) < 256
    runtime = bytes(
        [0x60, len(payload), 0x60, 12, 0x60, 0, 0x39, 0x60, len(payload), 0x60, 0, 0xF3]
    )
    runtime += payload
    initcode = bytes.fromhex(f"61{len(runtime):04x}3d81600a3d39f3") + runtime
    return env.deploy([], initcode)


def _deploy_venom_with_ctor_data(env, code, ctor_data, *, settings=None, input_bundle=None):
    out = _compile_venom(code, ["bytecode"], settings=settings, input_bundle=input_bundle)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x")) + ctor_data
    return env.deploy([], initcode)


def _call(env, contract, signature, args_schema=None, args=None):
    calldata = method_id(signature)
    if args_schema is not None:
        calldata += abi_encode(args_schema, args)
    return env.message_call(contract.address, data=calldata)


def test_inf_bytes_local_from_bounded(env):
    code = """
@external
def foo() -> Bytes[5]:
    x: Bytes[INF] = b"hello"
    return slice(x, 0, 5)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo()")) == (b"hello",)


def test_inf_string_local_from_bounded(env):
    code = """
@external
def foo() -> String[5]:
    x: String[INF] = "hello"
    return slice(x, 0, 5)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(string)", _call(env, c, "foo()")) == ("hello",)


def test_inf_bytes_and_string_locals_from_bounded_params(env):
    code = """
@external
def foo(a: Bytes[5], b: String[5]) -> (Bytes[5], String[5]):
    x: Bytes[INF] = a
    y: String[INF] = b
    return slice(x, 0, 5), slice(y, 0, 5)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "foo(bytes,string)", "(bytes,string)", (b"hello", "world"))
    assert abi_decode("(bytes,string)", ret) == (b"hello", "world")


def test_inf_bytes_and_string_external_return_from_bounded(env):
    code = """
@external
def foo() -> Bytes[INF]:
    return b"hello"

@external
def bar() -> String[INF]:
    return "world"
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo()")) == (b"hello",)
    assert abi_decode("(string)", _call(env, c, "bar()")) == ("world",)


def test_inf_bytes_external_return_from_local(env):
    code = """
@external
def foo() -> Bytes[INF]:
    x: Bytes[INF] = b"hello"
    x = b"dynamic"
    return x
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo()")) == (b"dynamic",)


def test_msg_data_as_inf_bytes_rvalue(env):
    code = """
@external
def foo() -> Bytes[INF]:
    return msg.data
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo()")) == (method_id("foo()"),)


def test_runtime_length_slice_returns_inf_bytes(env):
    code = """
@external
def from_local() -> Bytes[INF]:
    x: Bytes[INF] = b"hello"
    return slice(x, 0, len(x))

@external
def from_msg_data() -> Bytes[INF]:
    return slice(msg.data, 0, len(msg.data))
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "from_local()")) == (b"hello",)
    expected = method_id("from_msg_data()")
    assert abi_decode("(bytes)", _call(env, c, "from_msg_data()")) == (expected,)


def test_code_as_inf_bytes_rvalue(env):
    code = """
@external
def self_code() -> Bytes[INF]:
    return self.code

@external
def addr_code(addr: address) -> Bytes[INF]:
    return addr.code
    """

    c = _deploy_venom(env, code)
    expected = env.get_code(c.address)
    assert abi_decode("(bytes)", _call(env, c, "self_code()")) == (expected,)
    ret = _call(env, c, "addr_code(address)", "address", c.address)
    assert abi_decode("(bytes)", ret) == (expected,)


def test_inf_bytes_internal_forwarding(env):
    code = """
@internal
def _bar() -> Bytes[INF]:
    x: Bytes[INF] = b"hello"
    return x

@external
def foo() -> Bytes[INF]:
    return self._bar()
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo()")) == (b"hello",)


def test_inf_string_internal_nested_forwarding(env):
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

    c = _deploy_venom(env, code)
    assert abi_decode("(string)", _call(env, c, "foo()")) == ("hello",)


def test_empty_inf_bytes_internal_forwarding(env):
    code = """
@internal
def _bar() -> Bytes[INF]:
    x: Bytes[INF] = b""
    return x

@external
def foo() -> Bytes[INF]:
    return self._bar()
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo()")) == (b"",)


def test_inf_bytes_internal_forwarding_no_inline(env):
    code = """
@internal
def _bar() -> Bytes[INF]:
    x: Bytes[INF] = b"hello"
    return x

@external
def foo() -> Bytes[INF]:
    return self._bar()
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    assert abi_decode("(bytes)", _call(env, c, "foo()")) == (b"hello",)


def test_inf_bytes_external_param_roundtrip(env):
    code = """
@external
def echo(x: Bytes[INF]) -> Bytes[INF]:
    return x
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(bytes)", "(bytes)", (b"unbounded input",))
    assert abi_decode("(bytes)", ret) == (b"unbounded input",)


def test_large_inf_bytes_external_param_roundtrip(env):
    payload = bytes((i * 17) % 256 for i in range(2001))
    code = """
@external
def echo(x: Bytes[INF]) -> Bytes[INF]:
    return x
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_string_external_param_roundtrip(env):
    code = """
@external
def echo(x: String[INF]) -> String[INF]:
    return x
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(string)", "(string)", ("unbounded input",))
    assert abi_decode("(string)", ret) == ("unbounded input",)


def test_empty_inf_external_params(env):
    code = """
@external
def sizes(x: Bytes[INF], y: String[INF]) -> (uint256, uint256):
    return len(x), len(y)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "sizes(bytes,string)", "(bytes,string)", (b"", ""))
    assert abi_decode("(uint256,uint256)", ret) == (0, 0)


def test_inf_bytes_external_param_bounded_slice(env):
    code = """
@external
def first_three(x: Bytes[INF]) -> Bytes[3]:
    return slice(x, 0, 3)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "first_three(bytes)", "(bytes)", (b"abcdef",))
    assert abi_decode("(bytes)", ret) == (b"abc",)


def test_inf_bytes_external_kwarg_default_and_provided(env):
    code = """
@external
def echo(x: Bytes[INF] = b"default") -> Bytes[INF]:
    return x
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "echo()")) == (b"default",)

    ret = _call(env, c, "echo(bytes)", "(bytes)", (b"provided",))
    assert abi_decode("(bytes)", ret) == (b"provided",)


def test_inf_bytes_staticcall_return_roundtrip(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(bytes)", ret) == (b"external bytes",)


def test_large_inf_bytes_staticcall_return(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address,bytes)", "(address,bytes)", (target.address, payload))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_large_inf_bytes_staticcall_inf_arg_roundtrip(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address,bytes)", "(address,bytes)", (target.address, payload))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_bytes_staticcall_default_return_value(env):
    payload = b"live returndata"
    caller_code = """
interface Source:
    def data() -> Bytes[INF]: view

@external
def get(addr: address) -> Bytes[INF]:
    return staticcall Source(addr).data(default_return_value=b"fallback")
    """

    caller = _deploy_venom(env, caller_code)
    empty_target = _deploy_raw_returner(env, b"")
    ret = _call(env, caller, "get(address)", "address", empty_target.address)
    assert abi_decode("(bytes)", ret) == (b"fallback",)

    target = _deploy_raw_returner(env, abi_encode("(bytes)", (payload,)))
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_bytes_staticcall_tuple_return_roundtrip(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address,bytes)", "(address,bytes)", (target.address, payload))
    assert abi_decode("(uint256,bytes)", ret) == (31, payload)


def test_inf_bytes_staticcall_singleton_tuple_return(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address,bytes)", "(address,bytes)", (target.address, payload))
    assert ret == encode_singleton_bytes_tuple(payload)


def test_inf_bytes_staticcall_tuple_return_subscript(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address,bytes)", "(address,bytes)", (target.address, b"catdog"))
    assert abi_decode("(bytes)", ret) == (b"cat",)


def test_inf_bytes_staticcall_tuple_default_return_value(env):
    caller_code = """
interface Source:
    def pair() -> (uint256, Bytes[INF]): view

@external
def get(addr: address) -> (uint256, Bytes[INF]):
    return staticcall Source(addr).pair(default_return_value=(7, b"fallback"))
    """

    caller = _deploy_venom(env, caller_code)
    empty_target = _deploy_raw_returner(env, b"")
    ret = _call(env, caller, "get(address)", "address", empty_target.address)
    assert abi_decode("(uint256,bytes)", ret) == (7, b"fallback")

    target = _deploy_raw_returner(env, abi_encode("(uint256,bytes)", (9, b"live")))
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(uint256,bytes)", ret) == (9, b"live")


def test_inf_bytes_staticcall_tuple_default_return_value_from_bounded_local(env):
    caller_code = """
interface Source:
    def pair() -> (uint256, Bytes[INF]): view

@external
def get(addr: address) -> (uint256, Bytes[INF]):
    d: (uint256, Bytes[8]) = (7, b"fallback")
    return staticcall Source(addr).pair(default_return_value=d)
    """

    caller = _deploy_venom(env, caller_code)
    empty_target = _deploy_raw_returner(env, b"")
    ret = _call(env, caller, "get(address)", "address", empty_target.address)
    assert abi_decode("(uint256,bytes)", ret) == (7, b"fallback")


def test_inf_bytes_extcall_tuple_return_roundtrip(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address,bytes)", "(address,bytes)", (target.address, payload))
    assert abi_decode("(uint256,bytes)", ret) == (43, payload)


def test_inf_bytes_string_staticcall_tuple_multi_dynamic_return(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(
        env,
        caller,
        "get(address,bytes,string)",
        "(address,bytes,string)",
        (target.address, payload, text),
    )
    assert abi_decode("(bytes,uint256,string)", ret) == (payload, 53, text)


def test_inf_bytes_staticcall_inf_arg_with_static_args(env):
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

    target = _deploy_venom(env, code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address,bytes)", "(address,bytes)", (target.address, b"abcdef"))
    assert abi_decode("(bytes)", ret) == (b"abc",)


def test_inf_bytes_staticcall_snapshots_primitive_arg_before_later_mutation(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address,bytes)", "(address,bytes)", (target.address, b"cat"))
    assert abi_decode("(uint256,uint256)", ret) == (637, 2)


def test_inf_bytes_internal_call_snapshots_primitive_arg_before_later_mutation(env):
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

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "get(bytes)", "(bytes)", (b"cat",))
    assert abi_decode("(uint256,uint256)", ret) == (637, 2)


def test_inf_bytes_staticcall_inf_arg_with_bounded_dynamic_args(env):
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

    target = _deploy_venom(env, code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(
        env,
        caller,
        "get(address,bytes,bytes,bytes)",
        "(address,bytes,bytes,bytes)",
        (target.address, b"prelude", b"kitten", b"tail"),
    )
    assert abi_decode("(bytes)", ret) == (b"kitten",)


def test_inf_string_staticcall_return_roundtrip(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(string)", ret) == ("external string",)


def test_inf_string_staticcall_inf_arg_roundtrip(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    payload = "external string argument " * 80 + "tail"
    ret = _call(env, caller, "get(address,string)", "(address,string)", (target.address, payload))
    assert abi_decode("(string)", ret) == (payload,)


def test_inf_bytes_staticcall_return_bounded_slice(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(bytes)", ret) == (b"external",)


def test_empty_inf_bytes_staticcall_return(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(bytes)", ret) == (b"",)


def test_inf_bytes_staticcall_return_rejects_malformed_abi(env, tx_failed):
    caller_code = """
interface Source:
    def data() -> Bytes[INF]: view

@external
def get(addr: address) -> Bytes[INF]:
    return staticcall Source(addr).data()
    """

    caller = _deploy_venom(env, caller_code)

    def word(value):
        return value.to_bytes(32, "big")

    # Legacy accepts this non-canonical but in-bounds offset as an empty bytes
    # return; the INF path matches that leniency.
    target = _deploy_raw_returner(env, word(0))
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(bytes)", ret) == (b"",)

    malformed_payloads = [word(2**256 - 31), word(32), word(32) + word(33) + b"\x01" * 32]

    for payload in malformed_payloads:
        target = _deploy_raw_returner(env, payload)
        with tx_failed():
            _call(env, caller, "get(address)", "address", target.address)


def test_inf_bytes_staticcall_tuple_return_bounds_bounded_dynamic_member(env, tx_failed):
    caller_code = """
interface Source:
    def pair() -> (Bytes[4], Bytes[INF]): view

@external
def get(addr: address) -> (Bytes[4], Bytes[INF]):
    return staticcall Source(addr).pair()
    """

    def word(value):
        return value.to_bytes(32, "big")

    caller = _deploy_venom(env, caller_code)
    payload = word(2**251) + word(64) + word(0)
    target = _deploy_raw_returner(env, payload)

    with tx_failed():
        _call(env, caller, "get(address)", "address", target.address)


def test_inf_bytes_abi_decode_allows_missing_padding(env, tx_failed):
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF], unwrap_tuple=False)
    """

    c = _deploy_venom(env, code)

    def word(value):
        return value.to_bytes(32, "big")

    ret = _call(env, c, "dec(bytes)", "(bytes)", (word(31) + b"\x01" * 31,))
    assert abi_decode("(bytes)", ret) == (b"\x01" * 31,)

    with tx_failed():
        _call(env, c, "dec(bytes)", "(bytes)", (word(31) + b"\x01" * 30,))


def test_inf_bytes_extcall_return_roundtrip(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(bytes)", ret) == (b"mutable bytes",)


def test_inf_bytes_extcall_inf_arg_roundtrip(env):
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

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address,bytes)", "(address,bytes)", (target.address, b"mutable"))
    assert abi_decode("(bytes)", ret) == (b"mutable",)


def test_inf_bytes_json_abi_staticcall_return(env, make_input_bundle):
    target_code = """
@external
@view
def data() -> Bytes[INF]:
    return b"json abi bytes"
    """

    target = _deploy_venom(env, target_code)

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
    caller = _deploy_venom(env, caller_code, input_bundle=input_bundle)
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(bytes)", ret) == (b"json abi bytes",)


def test_inf_bytes_json_abi_external_call_freezes_bounded_arg_in_runtime_encoding(
    env, make_input_bundle
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

    target = _deploy_venom(env, target_code)
    input_bundle = make_input_bundle({"source.json": json.dumps(source_abi)})
    caller = _deploy_venom(env, caller_code, input_bundle=input_bundle)
    ret = _call(env, caller, "check(address,bytes)", "(address,bytes)", (target.address, b"cat"))
    assert abi_decode("(uint256,bytes)", ret) == (637, b"xy")


def test_inf_string_json_abi_staticcall_return(env, make_input_bundle):
    target_code = """
@external
@view
def data() -> String[INF]:
    return "json abi string"
    """

    target = _deploy_venom(env, target_code)

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
    caller = _deploy_venom(env, caller_code, input_bundle=input_bundle)
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(string)", ret) == ("json abi string",)


def test_inf_bytes_abi_encode_default_tuple(env):
    payload = bytes((i * 19) % 256 for i in range(2001))
    code = """
@external
def enc(x: Bytes[INF]) -> Bytes[INF]:
    return abi_encode(x)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "enc(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes)", ret) == (abi_encode("(bytes)", (payload,)),)


def test_inf_bytes_abi_encode_no_tuple(env):
    payload = bytes((i * 23) % 256 for i in range(2001))
    code = """
@external
def enc(x: Bytes[INF]) -> Bytes[INF]:
    return abi_encode(x, ensure_tuple=False)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "enc(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes)", ret) == (abi_encode("bytes", payload),)


def test_inf_bytes_abi_encode_method_id_and_static_args(env):
    payload = b"abcdef"
    code = """
@external
def enc(x: Bytes[INF]) -> Bytes[INF]:
    a: uint256 = 11
    b: uint256 = 22
    return abi_encode(a, x, b, method_id=method_id("foo(uint256,bytes,uint256)"))
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "enc(bytes)", "(bytes)", (payload,))
    expected = method_id("foo(uint256,bytes,uint256)")
    expected += abi_encode("(uint256,bytes,uint256)", (11, payload, 22))
    assert abi_decode("(bytes)", ret) == (expected,)


def test_inf_string_abi_encode_default_tuple(env):
    payload = "abi string " * 170 + "tail"
    code = """
@external
def enc(x: String[INF]) -> Bytes[INF]:
    return abi_encode(x)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "enc(string)", "(string)", (payload,))
    assert abi_decode("(bytes)", ret) == (abi_encode("(string)", (payload,)),)


def test_inf_bytes_abi_decode_default_tuple(env):
    payload = bytes((i * 37) % 256 for i in range(2001))
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF])
    """

    c = _deploy_venom(env, code)
    encoded = abi_encode("(bytes)", (payload,))
    ret = _call(env, c, "dec(bytes)", "(bytes)", (encoded,))
    assert abi_decode("(bytes)", ret) == (payload,)

    ret = _call(env, c, "dec(bytes)", "(bytes)", ((0).to_bytes(32, "big"),))
    assert abi_decode("(bytes)", ret) == (b"",)


def test_inf_bytes_abi_decode_no_tuple(env):
    payload = bytes((i * 41) % 256 for i in range(2001))
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF], unwrap_tuple=False)
    """

    c = _deploy_venom(env, code)
    encoded = abi_encode("bytes", payload)
    ret = _call(env, c, "dec(bytes)", "(bytes)", (encoded,))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_bounded_bytes_abi_decode_short_payload_zeroes_return_padding(env):
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[100]:
    return abi_decode(x, Bytes[100], unwrap_tuple=False)
    """

    c = _deploy_venom(env, code)

    def word(value):
        return value.to_bytes(32, "big")

    encoded = word(3) + b"abc" + b"\xff" * 29
    ret = _call(env, c, "dec(bytes)", "(bytes)", (encoded,))
    assert ret == word(32) + word(3) + b"abc" + b"\x00" * 29


def test_bounded_dynarray_abi_decode_bounds_dynamic_element_head(env, tx_failed):
    code = """
@external
def dec(x: Bytes[INF]) -> DynArray[Bytes[4], 2]:
    return abi_decode(x, DynArray[Bytes[4], 2], unwrap_tuple=False)
    """

    c = _deploy_venom(env, code)

    def word(value):
        return value.to_bytes(32, "big")

    payload = word(1) + word(2**251)
    with tx_failed():
        _call(env, c, "dec(bytes)", "(bytes)", (payload,))


def test_inf_bytes_abi_decode_rejects_malformed_payload(env, tx_failed):
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF])

@external
def dec_no_tuple(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF], unwrap_tuple=False)
    """

    c = _deploy_venom(env, code)

    def word(value):
        return value.to_bytes(32, "big")

    for payload in [word(32), word(32) + word(2) + b"a"]:
        with tx_failed():
            _call(env, c, "dec(bytes)", "(bytes)", (payload,))

    for payload in [b"", word(2) + b"a"]:
        with tx_failed():
            _call(env, c, "dec_no_tuple(bytes)", "(bytes)", (payload,))


def test_inf_string_abi_decode_default_tuple(env):
    payload = "decoded string " * 150 + "tail"
    code = """
@external
def dec(x: Bytes[INF]) -> String[INF]:
    return abi_decode(x, String[INF])
    """

    c = _deploy_venom(env, code)
    encoded = abi_encode("(string)", (payload,))
    ret = _call(env, c, "dec(bytes)", "(bytes)", (encoded,))
    assert abi_decode("(string)", ret) == (payload,)


def test_inf_bytes_abi_encode_decode_local_roundtrip(env):
    payload = bytes((i * 43) % 256 for i in range(2001))
    code = """
@external
def roundtrip(x: Bytes[INF]) -> Bytes[INF]:
    encoded: Bytes[INF] = abi_encode(x)
    return abi_decode(encoded, Bytes[INF])
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "roundtrip(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_bytes_concat_runtime_length(env):
    payload = bytes((i * 79) % 256 for i in range(2001))
    code = """
@external
def join(x: Bytes[INF]) -> Bytes[INF]:
    return concat(b"pre:", x, b":post")
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "join(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes)", ret) == (b"pre:" + payload + b":post",)


def test_inf_string_concat_runtime_length(env):
    payload = "concat string " * 170 + "tail"
    code = """
@external
def join(x: String[INF]) -> String[INF]:
    return concat("pre:", x, ":post")
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "join(string)", "(string)", (payload,))
    assert abi_decode("(string)", ret) == ("pre:" + payload + ":post",)


def test_inf_bytes_concat_trailing_bytesm_word_boundary(env):
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

    c = _deploy_venom(env, code)
    ret = _call(env, c, "join(bytes,bytes)", "(bytes,bytes)", (payload_a, payload_b))
    expected = payload_a + b"\xde" + payload_b + b"\xde\xad\xbe\xef"
    assert abi_decode("(bytes)", ret) == (expected,)


def test_inf_bytes_string_keccak256_runtime_length(env, keccak):
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

    c = _deploy_venom(env, code)
    ret = _call(env, c, "hash_bytes(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes32)", ret) == (keccak(payload),)
    ret = _call(env, c, "hash_string(string)", "(string)", (text,))
    assert abi_decode("(bytes32)", ret) == (keccak(text.encode()),)


def test_inf_string_uint2str(env):
    code = """
@external
def direct(x: uint256) -> String[INF]:
    return uint2str(x)

@external
def local(x: uint256) -> String[INF]:
    y: String[INF] = uint2str(x)
    return y
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "direct(uint256)", "uint256", 2**256 - 1)
    assert abi_decode("(string)", ret) == (str(2**256 - 1),)
    ret = _call(env, c, "local(uint256)", "uint256", 0)
    assert abi_decode("(string)", ret) == ("0",)


def test_inf_bytes_string_cross_convert(env, tx_failed):
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

    c = _deploy_venom(env, code)
    ret = _call(env, c, "to_bytes(string)", "(string)", ("hello",))
    assert abi_decode("(bytes)", ret) == (b"hello",)
    ret = _call(env, c, "to_string(bytes)", "(bytes)", (b"world",))
    assert abi_decode("(string)", ret) == ("world",)
    ret = _call(env, c, "inf_string_to_inf_bytes(string)", "(string)", ("hello",))
    assert abi_decode("(bytes)", ret) == (b"hello",)
    ret = _call(env, c, "inf_bytes_to_inf_string(bytes)", "(bytes)", (b"world",))
    assert abi_decode("(string)", ret) == ("world",)
    ret = _call(env, c, "bytes_to_bounded(bytes)", "(bytes)", (b"abcde",))
    assert abi_decode("(bytes)", ret) == (b"abcde",)
    ret = _call(env, c, "string_to_bounded(string)", "(string)", ("abcde",))
    assert abi_decode("(string)", ret) == ("abcde",)
    ret = _call(env, c, "bytes_to_string_bounded(bytes)", "(bytes)", (b"abcde",))
    assert abi_decode("(string)", ret) == ("abcde",)
    ret = _call(env, c, "string_to_bytes_bounded(string)", "(string)", ("abcde",))
    assert abi_decode("(bytes)", ret) == (b"abcde",)

    with tx_failed():
        _call(env, c, "bytes_to_bounded(bytes)", "(bytes)", (b"abcdef",))
    with tx_failed():
        _call(env, c, "string_to_bounded(string)", "(string)", ("abcdef",))


def test_inf_bytes_to_primitive_convert(env, tx_failed):
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

    c = _deploy_venom(env, code)
    ret = _call(env, c, "to_uint256(bytes)", "(bytes)", ((123).to_bytes(32, "big"),))
    assert abi_decode("(uint256)", ret) == (123,)
    ret = _call(env, c, "to_uint8(bytes)", "(bytes)", (b"\x7b",))
    assert abi_decode("(uint8)", ret) == (123,)
    ret = _call(env, c, "to_bytes4(bytes)", "(bytes)", (b"abcd",))
    assert abi_decode("(bytes4)", ret) == (b"abcd",)
    ret = _call(env, c, "to_bool(bytes)", "(bytes)", (b"\x00\x01",))
    assert abi_decode("(bool)", ret) == (True,)

    with tx_failed():
        _call(env, c, "to_uint256(bytes)", "(bytes)", (b"\x01" * 33,))
    with tx_failed():
        _call(env, c, "to_uint8(bytes)", "(bytes)", (b"\x01\x00",))
    with tx_failed():
        _call(env, c, "to_bytes4(bytes)", "(bytes)", (b"abcde",))


def test_inf_bytes_string_print(env):
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

    c = _deploy_venom(env, code)
    ret = _call(env, c, "log_values(bytes,string)", "(bytes,string)", (payload, text))
    assert abi_decode("(uint256,uint256,bytes32,bytes32)", ret) == (
        len(payload),
        len(text),
        hashlib.sha256(payload).digest(),
        hashlib.sha256(text.encode()).digest(),
    )


def test_inf_bytes_string_misc_builtins(env, tx_failed):
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

    c = _deploy_venom(env, code)
    payload = bytes((i * 17) % 256 for i in range(80))
    text = "sha string " * 20 + "tail"

    ret = _call(env, c, "hash_values(bytes,string)", "(bytes,string)", (payload, text))
    assert abi_decode("(bytes32,bytes32)", ret) == (
        hashlib.sha256(payload).digest(),
        hashlib.sha256(text.encode()).digest(),
    )

    ret = _call(env, c, "word_at(bytes,uint256)", "(bytes,uint256)", (payload, 7))
    assert abi_decode("(bytes32)", ret) == (payload[7:39],)

    ret = _call(
        env,
        c,
        "compare(bytes,bytes,string,string)",
        "(bytes,bytes,string,string)",
        (payload, payload, "cat", "kitten"),
    )
    assert abi_decode("(bool,bool)", ret) == (True, True)

    revert_data = method_id("NoFives()") + b"\x01\x02"
    with tx_failed(exc_text=revert_data.hex()):
        _call(env, c, "boom(bytes)", "(bytes)", (revert_data,))


def test_inf_bytes_raw_call_direct_return(env):
    payload = bytes((i * 47) % 256 for i in range(2001))
    code = """
IDENTITY: constant(address) = 0x0000000000000000000000000000000000000004

@external
def echo(x: Bytes[INF]) -> Bytes[INF]:
    return raw_call(IDENTITY, x, max_outsize=4096)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_bytes_raw_call_checkable_tuple_unpack(env):
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

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_bytes_raw_call_checkable_direct_tuple_return(env):
    payload = bytes((i * 59) % 256 for i in range(2001))
    code = """
IDENTITY: constant(address) = 0x0000000000000000000000000000000000000004

@external
def echo(x: Bytes[INF]) -> (bool, Bytes[INF]):
    return raw_call(IDENTITY, x, max_outsize=4096, revert_on_failure=False)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bool,bytes)", ret) == (True, payload)


def test_inf_bytes_raw_return(env):
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

    c = _deploy_venom(env, code)
    assert _call(env, c, "echo(bytes)", "(bytes)", (payload,)) == payload
    assert _call(env, c, "literal()") == b"literal"
    assert _call(env, c, "empty()") == b""


def test_inf_bytes_tuple_literal_return(env):
    payload = bytes((i * 73) % 256 for i in range(2001))
    code = """
@external
def pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    y: Bytes[INF] = x
    return 7, y
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "pair(bytes)", "(bytes)", (payload,))
    assert abi_decode("(uint256,bytes)", ret) == (7, payload)


def test_inf_string_tuple_literal_return(env):
    payload = "tuple string " * 170 + "tail"
    code = """
@external
def pair(x: String[INF]) -> (uint256, String[INF]):
    y: String[INF] = x
    return 9, y
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "pair(string)", "(string)", (payload,))
    assert abi_decode("(uint256,string)", ret) == (9, payload)


def test_inf_bytes_tuple_empty_literal_return(env):
    code = """
@external
def pair() -> (uint256, Bytes[INF]):
    return 1, b""
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256,bytes)", _call(env, c, "pair()")) == (1, b"")


def test_inf_bytes_tuple_ternary_return(env):
    code = """
@external
def choose(flag: bool) -> (uint256, Bytes[INF]):
    a: uint256 = 1
    b: uint256 = 2
    x: Bytes[INF] = b"cat"
    y: Bytes[INF] = b"kitten"
    return (a, x) if flag else (b, y)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256,bytes)", _call(env, c, "choose(bool)", "(bool)", (True,))) == (
        1,
        b"cat",
    )
    assert abi_decode("(uint256,bytes)", _call(env, c, "choose(bool)", "(bool)", (False,))) == (
        2,
        b"kitten",
    )


def test_inf_bytes_tuple_ternary_materializes_bounded_arm(env):
    code = """
@external
def choose(flag: bool, x: Bytes[INF]) -> (uint256, Bytes[INF]):
    d: (uint256, Bytes[4]) = (9, b"fish")
    n: uint256 = 7
    return d if flag else (n, x)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "choose(bool,bytes)", "(bool,bytes)", (True, b"cat"))
    assert abi_decode("(uint256,bytes)", ret) == (9, b"fish")
    ret = _call(env, c, "choose(bool,bytes)", "(bool,bytes)", (False, b"kitten"))
    assert abi_decode("(uint256,bytes)", ret) == (7, b"kitten")


def test_inf_bytes_singleton_tuple_literal_return(env):
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

    c = _deploy_venom(env, code)
    ret = _call(env, c, "from_arg(bytes)", "(bytes)", (payload,))
    assert ret == encode_singleton_bytes_tuple(payload)
    assert _call(env, c, "empty()") == encode_singleton_bytes_tuple(b"")


def test_inf_bytes_internal_tuple_return(env):
    payload = bytes((i * 89) % 256 for i in range(2001))
    code = """
@internal
def _pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return 11, x

@external
def pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return self._pair(x)
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "pair(bytes)", "(bytes)", (payload,))
    assert abi_decode("(uint256,bytes)", ret) == (11, payload)


def test_inf_bytes_internal_tuple_return_with_bounded_complex_member(env):
    payload = bytes((i * 90) % 256 for i in range(2001))
    code = """
@internal
def _pair(x: Bytes[INF]) -> (Bytes[5], Bytes[INF]):
    return b"small", x

@external
def pair(x: Bytes[INF]) -> (Bytes[5], Bytes[INF]):
    return self._pair(x)
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "pair(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes,bytes)", ret) == (b"small", payload)


def test_inf_bytes_internal_tuple_return_with_bounded_complex_member_after_inf(env):
    payload = bytes((i * 97) % 256 for i in range(2001))
    code = """
@internal
def _pair(x: Bytes[INF]) -> (Bytes[INF], Bytes[5]):
    return x, b"small"

@external
def pair(x: Bytes[INF]) -> (Bytes[INF], Bytes[5]):
    return self._pair(x)
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "pair(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes,bytes)", ret) == (payload, b"small")


def test_inf_bytes_internal_tuple_return_subscript(env):
    code = """
@internal
def _pair(x: Bytes[INF]) -> (uint256, Bytes[INF]):
    return 17, x

@external
def second(x: Bytes[INF]) -> Bytes[3]:
    return slice(self._pair(x)[1], 0, 3)
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "second(bytes)", "(bytes)", (b"cat",))
    assert abi_decode("(bytes)", ret) == (b"cat",)


def test_inf_string_internal_tuple_return_subscript(env):
    code = """
@internal
def _pair(x: String[INF]) -> (uint256, String[INF]):
    return 17, x

@external
def second(x: String[INF]) -> String[6]:
    return slice(self._pair(x)[1], 0, 6)
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "second(string)", "(string)", ("kitten",))
    assert abi_decode("(string)", ret) == ("kitten",)


def test_inf_bytes_string_internal_tuple_return_mixed_ordering(env):
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

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "mix(bytes,string)", "(bytes,string)", (payload, text))
    assert abi_decode("(bytes,uint256,string)", ret) == (payload, 23, text)


def test_inf_bytes_internal_tuple_return_swapped_dynamic_sources(env):
    code = """
@internal
def _swap(x: Bytes[INF], y: Bytes[INF]) -> (Bytes[INF], Bytes[INF]):
    return y, x

@external
def swap(x: Bytes[INF], y: Bytes[INF]) -> (Bytes[INF], Bytes[INF]):
    return self._swap(x, y)
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "swap(bytes,bytes)", "(bytes,bytes)", (b"first", b"second value"))
    assert abi_decode("(bytes,bytes)", ret) == (b"second value", b"first")


def test_inf_bytes_internal_tuple_return_many_ordinary_members(env):
    payload = bytes((i * 95) % 256 for i in range(2001))
    code = """
@internal
def _many(x: Bytes[INF]) -> (uint256, uint256, uint256, Bytes[INF]):
    return 1, 2, 3, x

@external
def many(x: Bytes[INF]) -> (uint256, uint256, uint256, Bytes[INF]):
    return self._many(x)
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "many(bytes)", "(bytes)", (payload,))
    assert abi_decode("(uint256,uint256,uint256,bytes)", ret) == (1, 2, 3, payload)


def test_inf_bytes_internal_singleton_tuple_return(env):
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

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "one(bytes)", "(bytes)", (payload,))
    assert ret == encode_singleton_bytes_tuple(payload)


def test_inf_bytes_internal_tuple_return_forwarding(env):
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

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "pair(bytes)", "(bytes)", (payload,))
    assert abi_decode("(uint256,bytes)", ret) == (19, payload)


def test_inf_bytes_internal_tuple_unpack(env):
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

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    assert abi_decode("(uint256,bytes)", _call(env, c, "unpack()")) == (13, b"kitten")


def test_inf_bytes_string_internal_tuple_multi_dynamic_return(env):
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

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "pair(bytes,string)", "(bytes,string)", (payload, text))
    assert abi_decode("(bytes,string)", ret) == (payload, text)


def test_inf_bytes_raw_create_bytecode_param(env):
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

    deployer = _deploy_venom(env, deployer_code)
    ret = _call(env, deployer, "deploy(bytes)", "(bytes)", (initcode,))
    addr = abi_decode("(address)", ret)[0]
    assert env.get_code(addr) == runtime


def test_inf_bytes_raw_create_oversized_initcode_no_revert(env):
    deployer_code = """
@external
def deploy(s: Bytes[INF]) -> address:
    return raw_create(s, revert_on_failure=False)
    """

    deployer = _deploy_venom(env, deployer_code)
    initcode = b"\x00" * (EIP_3860_LIMIT + 1)
    ret = _call(env, deployer, "deploy(bytes)", "(bytes)", (initcode,))
    assert abi_decode("(address)", ret) == ("0x0000000000000000000000000000000000000000",)


def test_inf_bytes_raw_create_oversized_initcode_reverts(env, tx_failed):
    deployer_code = """
@external
def deploy(s: Bytes[INF]) -> address:
    return raw_create(s)
    """

    deployer = _deploy_venom(env, deployer_code)
    initcode = b"\x00" * (EIP_3860_LIMIT + 1)
    with tx_failed():
        _call(env, deployer, "deploy(bytes)", "(bytes)", (initcode,))


def test_inf_bytes_raw_create_bytecode_local_with_ctor_arg(env):
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

    deployer = _deploy_venom(env, deployer_code)
    ret = _call(env, deployer, "deploy(bytes,uint256)", "(bytes,uint256)", (initcode, 42))
    addr = abi_decode("(address)", ret)[0]
    assert env.get_code(addr) == runtime
    ret = env.message_call(addr, data=method_id("foo()"))
    assert abi_decode("(uint256)", ret) == (42,)


def test_inf_bytes_raw_create_unbounded_ctor_arg(env):
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
    out = _compile_venom(to_deploy_code, ["bytecode"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    deployer_code = """
@external
def deploy(s: Bytes[INF], x: Bytes[INF]) -> address:
    return raw_create(s, x)
    """

    deployer = _deploy_venom(env, deployer_code)
    ret = _call(env, deployer, "deploy(bytes,bytes)", "(bytes,bytes)", (initcode, payload))
    addr = abi_decode("(address)", ret)[0]
    ret = env.message_call(addr, data=method_id("get()"))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_bytes_raw_create_snapshots_primitive_ctor_arg_before_later_mutation(env):
    child_code = """
stored: public(uint256)
marker: public(uint256)

@deploy
def __init__(a: uint256, x: Bytes[INF], marker: uint256):
    self.stored = a * 100 + len(x) * 10
    self.marker = marker
    """
    out = _compile_venom(child_code, ["bytecode"])
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

    deployer = _deploy_venom(env, deployer_code)
    ret = _call(env, deployer, "deploy(bytes,bytes)", "(bytes,bytes)", (initcode, b"cat"))
    addr = abi_decode("(address)", ret)[0]

    ret = env.message_call(addr, data=method_id("stored()"))
    assert abi_decode("(uint256)", ret) == (630,)
    ret = env.message_call(addr, data=method_id("marker()"))
    assert abi_decode("(uint256)", ret) == (7,)


def test_inf_bytes_create_from_blueprint_unbounded_ctor_arg(env):
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
    out = _compile_venom(to_deploy_code, ["blueprint_bytecode"])
    blueprint = env.deploy([], bytes.fromhex(out["blueprint_bytecode"].removeprefix("0x")))

    code = """
@external
def deploy(target: address, x: Bytes[INF]) -> address:
    return create_from_blueprint(target, x)
    """

    deployer = _deploy_venom(env, code)
    ret = _call(
        env, deployer, "deploy(address,bytes)", "(address,bytes)", (blueprint.address, payload)
    )
    addr = abi_decode("(address)", ret)[0]
    ret = env.message_call(addr, data=method_id("get()"))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_bytes_create_from_blueprint_raw_args_unbounded(env):
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
    out = _compile_venom(to_deploy_code, ["blueprint_bytecode"])
    blueprint = env.deploy([], bytes.fromhex(out["blueprint_bytecode"].removeprefix("0x")))
    raw_args = abi_encode("(bytes)", (payload,))

    code = """
@external
def deploy(target: address, args: Bytes[INF]) -> address:
    return create_from_blueprint(target, args, raw_args=True)
    """

    deployer = _deploy_venom(env, code)
    ret = _call(
        env, deployer, "deploy(address,bytes)", "(address,bytes)", (blueprint.address, raw_args)
    )
    addr = abi_decode("(address)", ret)[0]
    ret = env.message_call(addr, data=method_id("get()"))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_string_raw_create_unbounded_ctor_arg(env):
    payload = "raw create string " * 120 + "tail"
    to_deploy_code = """
stored_len: public(uint256)
stored_hash: public(bytes32)

@deploy
def __init__(x: String[INF]):
    self.stored_len = len(x)
    self.stored_hash = sha256(x)
    """
    out = _compile_venom(to_deploy_code, ["bytecode"])
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    deployer_code = """
@external
def deploy(s: Bytes[INF], x: String[INF]) -> address:
    return raw_create(s, x)
    """

    deployer = _deploy_venom(env, deployer_code)
    ret = _call(env, deployer, "deploy(bytes,string)", "(bytes,string)", (initcode, payload))
    addr = abi_decode("(address)", ret)[0]
    ret = env.message_call(addr, data=method_id("stored_len()"))
    assert abi_decode("(uint256)", ret) == (len(payload),)
    ret = env.message_call(addr, data=method_id("stored_hash()"))
    assert abi_decode("(bytes32)", ret) == (hashlib.sha256(payload.encode()).digest(),)


def test_inf_string_create_from_blueprint_unbounded_ctor_arg(env):
    payload = "blueprint string " * 130 + "tail"
    to_deploy_code = """
stored_len: public(uint256)
stored_hash: public(bytes32)

@deploy
def __init__(x: String[INF]):
    self.stored_len = len(x)
    self.stored_hash = sha256(x)
    """
    out = _compile_venom(to_deploy_code, ["blueprint_bytecode"])
    blueprint = env.deploy([], bytes.fromhex(out["blueprint_bytecode"].removeprefix("0x")))

    code = """
@external
def deploy(target: address, x: String[INF]) -> address:
    return create_from_blueprint(target, x)
    """

    deployer = _deploy_venom(env, code)
    ret = _call(
        env, deployer, "deploy(address,string)", "(address,string)", (blueprint.address, payload)
    )
    addr = abi_decode("(address)", ret)[0]
    ret = env.message_call(addr, data=method_id("stored_len()"))
    assert abi_decode("(uint256)", ret) == (len(payload),)
    ret = env.message_call(addr, data=method_id("stored_hash()"))
    assert abi_decode("(bytes32)", ret) == (hashlib.sha256(payload.encode()).digest(),)


@pytest.mark.parametrize("call", ["raw_create(s, (x, y))", "create_from_blueprint(target, (x, y))"])
def test_create_rejects_nested_inf_ctor_arg(call):
    target_arg = "target: address, " if call.startswith("create_from_blueprint") else ""
    code = f"""
@external
def deploy({target_arg}s: Bytes[INF], x: Bytes[INF], y: uint256) -> address:
    return {call}
    """

    with pytest.raises(
        StructureException,
        match="constructor arguments cannot contain nested unbounded sequence types",
    ):
        compile_code(code, settings=_venom_settings())


def test_inf_bytes_raw_log_data(env):
    payload = bytes((i * 61) % 256 for i in range(2001))
    code = """
@external
def emit_raw(x: Bytes[INF]):
    raw_log([], x)
    """

    c = _deploy_venom(env, code)
    _call(env, c, "emit_raw(bytes)", "(bytes)", (payload,))
    assert env.get_logs(c, raw=True)[0][1] == payload


def test_inf_bytes_constructor_arg(env):
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

    c = _deploy_venom_with_ctor_data(env, code, abi_encode("(bytes)", (payload,)))
    assert abi_decode("(bytes)", _call(env, c, "get()")) == (payload,)


def test_inf_bytes_constructor_arg_allows_truncated_data(env):
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

    c = _deploy_venom_with_ctor_data(env, code, word(32) + word(2001))
    assert abi_decode("(uint256)", _call(env, c, "ok()")) == (1,)


def test_inf_bytes_external_param_rejects_truncated_calldata(env, tx_failed):
    code = """
@external
def length(x: Bytes[INF]) -> uint256:
    return len(x)
    """

    c = _deploy_venom(env, code)

    def word(value):
        return value.to_bytes(32, "big")

    calldata = method_id("length(bytes)") + word(32) + word(2001)
    with tx_failed():
        env.message_call(c.address, data=calldata)

    calldata = method_id("length(bytes)") + word(0)
    assert abi_decode("(uint256)", env.message_call(c.address, data=calldata)) == (0,)


def test_inf_bytes_external_param_allows_missing_padding(env):
    code = """
@external
def length(x: Bytes[INF]) -> uint256:
    return len(x)
    """

    c = _deploy_venom(env, code)

    def word(value):
        return value.to_bytes(32, "big")

    calldata = method_id("length(bytes)") + word(32) + word(3) + b"cat"
    assert abi_decode("(uint256)", env.message_call(c.address, data=calldata)) == (3,)


def test_inf_bytes_internal_arg_roundtrip(env):
    payload = bytes((i * 13) % 256 for i in range(2001))
    code = """
@internal
def _echo(x: Bytes[INF]) -> Bytes[INF]:
    return x

@external
def echo(x: Bytes[INF]) -> Bytes[INF]:
    return self._echo(x)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes)", ret) == (payload,)


def test_inf_bytes_internal_arg_is_copied(env):
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

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "check()")) == (b"abc",)


def test_inf_bytes_internal_arg_reassignment_does_not_mutate_caller(env):
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

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes,bytes)", _call(env, c, "check()")) == (b"def", b"abc")


def test_empty_inf_bytes_and_string_locals(env):
    code = """
@external
def foo() -> (uint256, uint256):
    x: Bytes[INF] = b""
    y: String[INF] = ""
    return len(x), len(y)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256,uint256)", _call(env, c, "foo()")) == (0, 0)


def test_empty_inf_bytes_and_string_builtin(env):
    code = """
@external
def foo() -> Bytes[INF]:
    return empty(Bytes[INF])

@external
def bar() -> String[INF]:
    return empty(String[INF])
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo()")) == (b"",)
    assert abi_decode("(string)", _call(env, c, "bar()")) == ("",)


def test_empty_inf_bytes_dynamic_tuple_builtin(env):
    code = """
@external
def value() -> (uint256, Bytes[INF]):
    return empty((uint256, Bytes[INF]))
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256,bytes)", _call(env, c, "value()")) == (0, b"")


def test_empty_inf_string_dynamic_tuple_builtin(env):
    code = """
@external
def value() -> (uint256, String[INF]):
    return empty((uint256, String[INF]))
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256,string)", _call(env, c, "value()")) == (0, "")


def test_empty_nested_inf_aggregate_rejected():
    code = """
@external
def value() -> uint256:
    return len(empty(((Bytes[INF],), uint256))[0][0])
    """

    with pytest.raises(StructureException, match="inside aggregate types"):
        compile_code(code, settings=_venom_settings())


def test_inf_bytes_local_reassignment_larger_and_smaller(env):
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

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "grow()")) == (b"kitten",)
    assert abi_decode("(bytes)", _call(env, c, "shrink()")) == (b"cat",)


def test_inf_bytes_local_reassignment_in_if(env):
    code = """
@external
def foo(flag: bool) -> Bytes[3]:
    x: Bytes[INF] = b"abc"
    if flag:
        x = b"defg"
    return slice(x, 0, 3)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo(bool)", "bool", False)) == (b"abc",)
    assert abi_decode("(bytes)", _call(env, c, "foo(bool)", "bool", True)) == (b"def",)


def test_inf_bytes_local_reassignment_in_loop(env):
    code = """
@external
def foo(flag: bool) -> Bytes[3]:
    x: Bytes[INF] = b"one"
    for i: uint256 in range(2):
        if flag and i == 1:
            x = b"two"
    return slice(x, 0, 3)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo(bool)", "bool", False)) == (b"one",)
    assert abi_decode("(bytes)", _call(env, c, "foo(bool)", "bool", True)) == (b"two",)
