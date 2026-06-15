import json

from tests.evm_backends.abi import abi_decode, abi_encode
from vyper.compiler import compile_code
from vyper.compiler.settings import Settings, VenomOptimizationFlags
from vyper.utils import keccak256, method_id


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

    malformed_payloads = [word(0), word(2**256 - 31), word(32), word(32) + word(33) + b"\x01" * 32]

    for payload in malformed_payloads:
        target = _deploy_raw_returner(env, payload)
        with tx_failed():
            _call(env, caller, "get(address)", "address", target.address)


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


def test_inf_bytes_event_data(env):
    payload = bytes((i * 67) % 256 for i in range(2001))
    code = """
event E:
    x: Bytes[INF]

@external
def emit_event(x: Bytes[INF]):
    log E(x=x)
    """

    c = _deploy_venom(env, code)
    _call(env, c, "emit_event(bytes)", "(bytes)", (payload,))
    assert env.get_logs(c, raw=True)[0][1] == abi_encode("(bytes)", (payload,))


def test_indexed_inf_bytes_event_topic(env):
    payload = bytes((i * 71) % 256 for i in range(2001))
    code = """
event E:
    x: indexed(Bytes[INF])

@external
def emit_event(x: Bytes[INF]):
    log E(x=x)
    """

    c = _deploy_venom(env, code)
    _call(env, c, "emit_event(bytes)", "(bytes)", (payload,))
    topics, data = env.get_logs(c, raw=True)[0]
    assert topics[1] == keccak256(payload)
    assert data == b""


def test_inf_string_event_data_with_static_args(env):
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

    c = _deploy_venom(env, code)
    _call(env, c, "emit_event(string)", "(string)", (payload,))
    assert env.get_logs(c, raw=True)[0][1] == abi_encode(
        "(uint256,string,uint256)", (11, payload, 22)
    )


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
