from tests.evm_backends.abi import abi_decode, abi_encode
from vyper.compiler import compile_code
from vyper.compiler.settings import Settings, VenomOptimizationFlags
from vyper.utils import method_id


def _venom_settings(*, disable_inlining=False):
    settings = Settings(experimental_codegen=True)
    if disable_inlining:
        settings.venom_flags = VenomOptimizationFlags(disable_inlining=True)
    return settings


def _compile_venom(code, output_formats, *, settings=None):
    return compile_code(code, output_formats=output_formats, settings=settings or _venom_settings())


def _deploy_venom(env, code, *, settings=None):
    out = _compile_venom(code, ["bytecode"], settings=settings)
    return env.deploy([], bytes.fromhex(out["bytecode"].removeprefix("0x")))


def _deploy_venom_with_ctor_data(env, code, ctor_data, *, settings=None):
    out = _compile_venom(code, ["bytecode"], settings=settings)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x")) + ctor_data
    return env.deploy([], initcode)


def _deploy_raw_returner(env, payload):
    assert len(payload) < 256
    runtime = bytes(
        [0x60, len(payload), 0x60, 12, 0x60, 0, 0x39, 0x60, len(payload), 0x60, 0, 0xF3]
    )
    runtime += payload
    initcode = bytes.fromhex(f"61{len(runtime):04x}3d81600a3d39f3") + runtime
    return env.deploy([], initcode)


def _call(env, contract, signature, args_schema=None, args=None):
    calldata = method_id(signature)
    if args_schema is not None:
        calldata += abi_encode(args_schema, args)
    return env.message_call(contract.address, data=calldata)


def test_inf_dynarray_local_from_literal(env):
    code = """
@external
def foo() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1, 2, 3]
    return x
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256[])", _call(env, c, "foo()")) == ([1, 2, 3],)


def test_inf_dynarray_local_from_bounded(env):
    code = """
@external
def foo() -> DynArray[uint256, INF]:
    bounded: DynArray[uint256, 5] = [11, 22, 33]
    x: DynArray[uint256, INF] = bounded
    return x
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256[])", _call(env, c, "foo()")) == ([11, 22, 33],)


def test_inf_dynarray_external_param_roundtrip(env):
    code = """
@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(uint256[])", "(uint256[])", ([4, 5, 6, 7],))
    assert abi_decode("(uint256[])", ret) == ([4, 5, 6, 7],)


def test_empty_inf_dynarray_external_param_roundtrip(env):
    code = """
@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(uint256[])", "(uint256[])", ([],))
    assert abi_decode("(uint256[])", ret) == ([],)


def test_large_inf_dynarray_external_param_roundtrip(env):
    payload = [i * 17 for i in range(2001)]
    code = """
@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(uint256[])", "(uint256[])", (payload,))
    assert abi_decode("(uint256[])", ret) == (payload,)


def test_inf_dynarray_reassignment_larger_and_smaller(env):
    code = """
@external
def grow() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1]
    x = [1, 2, 3, 4, 5]
    return x

@external
def shrink() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1, 2, 3, 4, 5]
    x = [9]
    return x
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256[])", _call(env, c, "grow()")) == ([1, 2, 3, 4, 5],)
    assert abi_decode("(uint256[])", _call(env, c, "shrink()")) == ([9],)


def test_inf_dynarray_if_reassignment(env):
    code = """
@external
def pick(flag: bool) -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1, 2]
    if flag:
        x = [10, 20, 30, 40]
    else:
        x = [7]
    return x
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "pick(bool)", "bool", True)
    assert abi_decode("(uint256[])", ret) == ([10, 20, 30, 40],)
    ret = _call(env, c, "pick(bool)", "bool", False)
    assert abi_decode("(uint256[])", ret) == ([7],)


def test_inf_dynarray_append_reallocates(env):
    code = """
@external
def grow(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    y: DynArray[uint256, INF] = x
    y.append(99)
    y.append(123)
    return y
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "grow(uint256[])", "(uint256[])", ([1, 2, 3],))
    assert abi_decode("(uint256[])", ret) == ([1, 2, 3, 99, 123],)


def test_inf_dynarray_for_loop(env):
    code = """
@external
def total(x: DynArray[uint256, INF]) -> uint256:
    ret: uint256 = 0
    for item: uint256 in x:
        ret += item
    return ret
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "total(uint256[])", "(uint256[])", ([5, 8, 13, 21],))
    assert abi_decode("(uint256)", ret) == (47,)


def test_inf_dynarray_internal_arg_return_roundtrip(env):
    code = """
@internal
def _echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x

@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return self._echo(x)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(uint256[])", "(uint256[])", ([3, 1, 4, 1, 5],))
    assert abi_decode("(uint256[])", ret) == ([3, 1, 4, 1, 5],)


def test_inf_dynarray_internal_arg_return_no_inline(env):
    code = """
@internal
def _echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x

@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return self._echo(x)
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "echo(uint256[])", "(uint256[])", ([8, 6, 7, 5, 3, 0, 9],))
    assert abi_decode("(uint256[])", ret) == ([8, 6, 7, 5, 3, 0, 9],)


def test_inf_dynarray_internal_tuple_return_no_inline(env):
    payload = [i * 19 for i in range(2001)]
    code = """
@internal
def _pair(x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]):
    return 17, x

@external
def pair(x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]):
    return self._pair(x)
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "pair(uint256[])", "(uint256[])", (payload,))
    assert abi_decode("(uint256,uint256[])", ret) == (17, payload)


def test_inf_dynarray_internal_tuple_unpack_no_inline(env):
    code = """
@internal
def _pair() -> (uint256, DynArray[uint256, INF]):
    return 23, [4, 5, 6]

@external
def unpack() -> (uint256, uint256, uint256):
    a: uint256 = 0
    b: DynArray[uint256, INF] = []
    a, b = self._pair()
    return a, len(b), b[2]
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    assert abi_decode("(uint256,uint256,uint256)", _call(env, c, "unpack()")) == (23, 3, 6)


def test_inf_dynarray_external_kwarg_default_and_provided(env):
    code = """
@external
def echo(x: DynArray[uint256, INF] = [12, 34]) -> DynArray[uint256, INF]:
    return x
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256[])", _call(env, c, "echo()")) == ([12, 34],)

    ret = _call(env, c, "echo(uint256[])", "(uint256[])", ([56, 78, 90],))
    assert abi_decode("(uint256[])", ret) == ([56, 78, 90],)


def test_inf_dynarray_constructor_param(env):
    code = """
stored_len: immutable(uint256)
stored_item: immutable(uint256)

@deploy
def __init__(x: DynArray[uint256, INF]):
    stored_len = len(x)
    stored_item = x[3]

@external
def get() -> (uint256, uint256):
    return stored_len, stored_item
    """

    ctor_data = abi_encode("(uint256[])", ([11, 22, 33, 44, 55],))
    c = _deploy_venom_with_ctor_data(env, code, ctor_data)
    assert abi_decode("(uint256,uint256)", _call(env, c, "get()")) == (5, 44)


def test_inf_dynarray_constructor_param_allows_truncated_data(env):
    code = """
@deploy
def __init__(x: DynArray[uint256, INF]):
    pass

@external
def ok() -> uint256:
    return 1
    """

    def word(value):
        return value.to_bytes(32, "big")

    c = _deploy_venom_with_ctor_data(env, code, word(32) + word(2) + word(1))
    assert abi_decode("(uint256)", _call(env, c, "ok()")) == (1,)


def test_inf_dynarray_staticcall_return_roundtrip(env):
    target_code = """
@external
@view
def data() -> DynArray[uint256, INF]:
    return [10, 20, 30]
    """

    caller_code = """
interface Source:
    def data() -> DynArray[uint256, INF]: view

@external
def get(addr: address) -> DynArray[uint256, INF]:
    return staticcall Source(addr).data()
    """

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(uint256[])", ret) == ([10, 20, 30],)


def test_inf_dynarray_staticcall_return_rejects_wrapped_length(env, tx_failed):
    caller_code = """
interface Source:
    def data() -> DynArray[uint256, INF]: view

@external
def get(addr: address) -> DynArray[uint256, INF]:
    return staticcall Source(addr).data()
    """

    caller = _deploy_venom(env, caller_code)

    def word(value):
        return value.to_bytes(32, "big")

    target = _deploy_raw_returner(env, word(32) + word(2**251))
    with tx_failed():
        _call(env, caller, "get(address)", "address", target.address)


def test_inf_dynarray_staticcall_default_return_value(env):
    payload = [10, 20, 30]
    caller_code = """
interface Source:
    def data() -> DynArray[uint256, INF]: view

@external
def get(addr: address) -> DynArray[uint256, INF]:
    return staticcall Source(addr).data(default_return_value=[7, 8, 9])
    """

    caller = _deploy_venom(env, caller_code)
    empty_target = _deploy_raw_returner(env, b"")
    ret = _call(env, caller, "get(address)", "address", empty_target.address)
    assert abi_decode("(uint256[])", ret) == ([7, 8, 9],)

    target = _deploy_raw_returner(env, abi_encode("(uint256[])", (payload,)))
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(uint256[])", ret) == (payload,)


def test_inf_dynarray_staticcall_tuple_return_roundtrip(env):
    payload = [i * 43 for i in range(2001)]
    target_code = """
@external
@view
def pair(x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]):
    return 41, x
    """

    caller_code = """
interface Source:
    def pair(x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]): view

@external
def get(addr: address, x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]):
    return staticcall Source(addr).pair(x)
    """

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(
        env, caller, "get(address,uint256[])", "(address,uint256[])", (target.address, payload)
    )
    assert abi_decode("(uint256,uint256[])", ret) == (41, payload)


def test_large_inf_dynarray_staticcall_inf_arg_roundtrip(env):
    payload = [i * 29 for i in range(2001)]
    target_code = """
@external
@view
def data(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    caller_code = """
interface Source:
    def data(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]: view

@external
def get(addr: address, x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return staticcall Source(addr).data(x)
    """

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(
        env, caller, "get(address,uint256[])", "(address,uint256[])", (target.address, payload)
    )
    assert abi_decode("(uint256[])", ret) == (payload,)


def test_inf_dynarray_extcall_inf_arg_roundtrip(env):
    target_code = """
@external
def data(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    caller_code = """
interface Source:
    def data(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]: nonpayable

@external
def get(addr: address, x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return extcall Source(addr).data(x)
    """

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(
        env, caller, "get(address,uint256[])", "(address,uint256[])", (target.address, [9, 8, 7])
    )
    assert abi_decode("(uint256[])", ret) == ([9, 8, 7],)


def test_inf_dynarray_abi_encode_default_tuple(env):
    payload = [i * 31 for i in range(2001)]
    code = """
@external
def enc(x: DynArray[uint256, INF]) -> Bytes[INF]:
    return abi_encode(x)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "enc(uint256[])", "(uint256[])", (payload,))
    assert abi_decode("(bytes)", ret) == (abi_encode("(uint256[])", (payload,)),)


def test_inf_dynarray_abi_encode_no_tuple(env):
    payload = [i * 37 for i in range(2001)]
    code = """
@external
def enc(x: DynArray[uint256, INF]) -> Bytes[INF]:
    return abi_encode(x, ensure_tuple=False)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "enc(uint256[])", "(uint256[])", (payload,))
    assert abi_decode("(bytes)", ret) == (abi_encode("uint256[]", payload),)


def test_inf_dynarray_abi_encode_method_id_and_static_args(env):
    payload = [5, 8, 13, 21]
    code = """
@external
def enc(a: uint256, x: DynArray[uint256, INF], b: uint256) -> Bytes[INF]:
    return abi_encode(a, x, b, method_id=method_id("foo(uint256,uint256[],uint256)"))
    """

    c = _deploy_venom(env, code)
    ret = _call(
        env, c, "enc(uint256,uint256[],uint256)", "(uint256,uint256[],uint256)", (11, payload, 22)
    )
    expected = method_id("foo(uint256,uint256[],uint256)")
    expected += abi_encode("(uint256,uint256[],uint256)", (11, payload, 22))
    assert abi_decode("(bytes)", ret) == (expected,)


def test_inf_dynarray_abi_decode_default_tuple(env):
    payload = [i * 41 for i in range(2001)]
    code = """
@external
def dec(x: Bytes[INF]) -> DynArray[uint256, INF]:
    return abi_decode(x, DynArray[uint256, INF])
    """

    c = _deploy_venom(env, code)
    encoded = abi_encode("(uint256[])", (payload,))
    ret = _call(env, c, "dec(bytes)", "(bytes)", (encoded,))
    assert abi_decode("(uint256[])", ret) == (payload,)


def test_inf_dynarray_abi_decode_no_tuple(env):
    payload = [i * 43 for i in range(2001)]
    code = """
@external
def dec(x: Bytes[INF]) -> DynArray[uint256, INF]:
    return abi_decode(x, DynArray[uint256, INF], unwrap_tuple=False)
    """

    c = _deploy_venom(env, code)
    encoded = abi_encode("uint256[]", payload)
    ret = _call(env, c, "dec(bytes)", "(bytes)", (encoded,))
    assert abi_decode("(uint256[])", ret) == (payload,)


def test_inf_dynarray_abi_decode_rejects_malformed_payload(env, tx_failed):
    code = """
@external
def dec(x: Bytes[INF]) -> DynArray[uint256, INF]:
    return abi_decode(x, DynArray[uint256, INF])

@external
def dec_no_tuple(x: Bytes[INF]) -> DynArray[uint256, INF]:
    return abi_decode(x, DynArray[uint256, INF], unwrap_tuple=False)
    """

    c = _deploy_venom(env, code)

    def word(value):
        return value.to_bytes(32, "big")

    ret = _call(env, c, "dec(bytes)", "(bytes)", (word(0),))
    assert abi_decode("(uint256[])", ret) == ([],)

    for payload in [word(32), word(32) + word(2) + word(1)]:
        with tx_failed():
            _call(env, c, "dec(bytes)", "(bytes)", (payload,))

    with tx_failed():
        _call(env, c, "dec_no_tuple(bytes)", "(bytes)", (word(2) + word(1),))


def test_inf_dynarray_abi_encode_decode_local_roundtrip(env):
    payload = [i * 47 for i in range(2001)]
    code = """
@external
def roundtrip(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    encoded: Bytes[INF] = abi_encode(x)
    return abi_decode(encoded, DynArray[uint256, INF])
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "roundtrip(uint256[])", "(uint256[])", (payload,))
    assert abi_decode("(uint256[])", ret) == (payload,)


def test_inf_dynarray_internal_tuple_return_coerces_bounded_complex_member(env):
    payload = bytes((i * 49) % 256 for i in range(2001))
    code = """
@internal
def _pair(x: Bytes[INF]) -> (DynArray[Bytes[65], 3], Bytes[INF]):
    y: DynArray[Bytes[33], 3] = [b"cat", b"kitten"]
    return y, x

@external
def pair(x: Bytes[INF]) -> (DynArray[Bytes[65], 3], Bytes[INF]):
    return self._pair(x)
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "pair(bytes)", "(bytes)", (payload,))
    assert abi_decode("(bytes[],bytes)", ret) == ([b"cat", b"kitten"], payload)


def test_inf_dynarray_external_param_rejects_truncated_calldata(env, tx_failed):
    code = """
@external
def length(x: DynArray[uint256, INF]) -> uint256:
    return len(x)
    """

    c = _deploy_venom(env, code)

    def word(value):
        return value.to_bytes(32, "big")

    calldata = method_id("length(uint256[])") + word(32) + word(2) + word(1)
    with tx_failed():
        env.message_call(c.address, data=calldata)

    calldata = method_id("length(uint256[])") + word(0)
    assert abi_decode("(uint256)", env.message_call(c.address, data=calldata)) == (0,)
