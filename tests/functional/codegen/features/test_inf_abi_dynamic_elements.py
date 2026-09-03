import pytest

from tests.evm_backends.abi import abi_decode, abi_encode
from vyper.compiler import compile_code
from vyper.utils import method_id


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


def _deploy_raw_returner(env, payload):
    assert len(payload) < 256
    runtime = bytes(
        [0x60, len(payload), 0x60, 12, 0x60, 0, 0x39, 0x60, len(payload), 0x60, 0, 0xF3]
    )
    runtime += payload
    initcode = bytes.fromhex(f"61{len(runtime):04x}3d81600a3d39f3") + runtime
    return env.deploy([], initcode)


def _word(value):
    return value.to_bytes(32, "big")


def _bytes_payload(n):
    return [bytes([(i * 7) % 256]) * (i % 64) for i in range(n)]


def _string_payload(n):
    return ["".join(chr(97 + (i + j) % 26) for j in range(i % 64)) for i in range(n)]


_ELEMENT_CASES = [
    ("Bytes[512]", "bytes", _bytes_payload),
    ("String[64]", "string", _string_payload),
]


@pytest.mark.parametrize("n", [0, 1, 3, 300])
@pytest.mark.parametrize(("elem_t", "abi_t", "make_payload"), _ELEMENT_CASES)
def test_inf_abi_dynamic_elements_calldata_arg(get_contract, elem_t, abi_t, make_payload, n):
    payload = make_payload(n)
    code = f"""
@external
def length(xs: DynArray[{elem_t}, INF]) -> uint256:
    return len(xs)

@external
def get(xs: DynArray[{elem_t}, INF], i: uint256) -> {elem_t}:
    return xs[i]

@external
def total_len(xs: DynArray[{elem_t}, INF]) -> uint256:
    total: uint256 = 0
    for x: {elem_t} in xs:
        total += len(x)
    return total
    """

    c = get_contract(code)
    assert c.length(payload) == n
    assert c.total_len(payload) == sum(len(x) for x in payload)
    for i in sorted({0, n // 2, n - 1} if n > 0 else set()):
        assert c.get(payload, i) == payload[i]


@pytest.mark.parametrize(("elem_t", "abi_t", "make_payload"), _ELEMENT_CASES)
def test_inf_abi_dynamic_elements_return_from_calldata(get_contract, elem_t, abi_t, make_payload):
    payload = make_payload(37)
    code = f"""
@external
def echo(xs: DynArray[{elem_t}, INF]) -> DynArray[{elem_t}, INF]:
    return xs
    """

    c = get_contract(code)
    assert c.echo(payload) == payload
    assert c.echo([]) == []


def test_inf_bytes_array_return_built_by_append(get_contract):
    code = """
@external
def build(n: uint256) -> DynArray[Bytes[512], INF]:
    xs: DynArray[Bytes[512], INF] = []
    for i: uint256 in range(n, bound=1000):
        xs.append(concat(b"item", convert(i, bytes32)))
    return xs
    """

    c = get_contract(code)
    for n in (0, 1, 5, 130):
        assert c.build(n) == [b"item" + _word(i) for i in range(n)]


def test_inf_string_array_return_built_by_append(get_contract):
    code = """
@external
def build(xs: DynArray[String[64], INF], extra: String[64]) -> DynArray[String[64], INF]:
    ys: DynArray[String[64], INF] = xs
    ys.append(extra)
    ys.append("")
    ys.append(extra)
    return ys
    """

    c = get_contract(code)
    payload = _string_payload(9)
    assert c.build(payload, "tail") == payload + ["tail", "", "tail"]
    assert c.build([], "x" * 64) == ["x" * 64, "", "x" * 64]


def test_inf_bytes_array_extcall_return(get_contract):
    target_code = """
@external
@view
def data() -> DynArray[Bytes[512], INF]:
    return [b"a", b"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", b""]
    """

    caller_code = """
interface Source:
    def data() -> DynArray[Bytes[512], INF]: view

@external
def get(addr: address) -> DynArray[Bytes[512], INF]:
    return staticcall Source(addr).data()

@external
def second(addr: address) -> Bytes[512]:
    xs: DynArray[Bytes[512], INF] = staticcall Source(addr).data()
    return xs[1]
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address) == [b"a", b"b" * 64, b""]
    assert caller.second(target.address) == b"b" * 64


def test_inf_string_array_extcall_arg(get_contract):
    target_code = """
@external
def join(xs: DynArray[String[64], INF]) -> uint256:
    total: uint256 = 0
    for x: String[64] in xs:
        total += len(x)
    return total
    """

    caller_code = """
interface Target:
    def join(xs: DynArray[String[64], INF]) -> uint256: nonpayable

@external
def call(addr: address, xs: DynArray[String[64], INF]) -> uint256:
    return extcall Target(addr).join(xs)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    payload = _string_payload(20)
    assert caller.call(target.address, payload) == sum(len(x) for x in payload)


def test_inf_bytes_array_abi_encode_decode_roundtrip(get_contract):
    code = """
@external
def enc(xs: DynArray[Bytes[512], INF]) -> Bytes[INF]:
    return abi_encode(xs)

@external
def enc_method_id(xs: DynArray[Bytes[512], INF]) -> Bytes[INF]:
    return abi_encode(xs, method_id=method_id("foo(bytes[])"))

@external
def dec(data: Bytes[INF]) -> DynArray[Bytes[512], INF]:
    return abi_decode(data, DynArray[Bytes[512], INF])

@external
def roundtrip(xs: DynArray[Bytes[512], INF]) -> DynArray[Bytes[512], INF]:
    encoded: Bytes[INF] = abi_encode(xs)
    return abi_decode(encoded, DynArray[Bytes[512], INF])
    """

    c = get_contract(code)
    payload = _bytes_payload(25)
    encoded = abi_encode("(bytes[])", (payload,))
    assert c.enc(payload) == encoded
    assert c.enc_method_id(payload) == method_id("foo(bytes[])") + encoded
    assert c.dec(encoded) == payload
    assert c.roundtrip(payload) == payload
    assert c.roundtrip([]) == []


def test_inf_bytes_array_event(env, get_contract):
    code = """
event E:
    n: uint256
    xs: DynArray[Bytes[512], INF]

@external
def emit_event(xs: DynArray[Bytes[512], INF]):
    log E(n=len(xs), xs=xs)
    """

    c = get_contract(code)
    payload = _bytes_payload(11)
    c.emit_event(payload)
    assert env.get_logs(c, raw=True)[0][1] == abi_encode(
        "(uint256,bytes[])", (len(payload), payload)
    )


def test_inf_bytes_array_rejects_count_beyond_payload(env, get_contract, tx_failed):
    code = """
@external
def length(xs: DynArray[Bytes[512], INF]) -> uint256:
    return len(xs)
    """

    c = get_contract(code)
    selector = method_id("length(bytes[])")

    # one head word of payload, so at most one element can be claimed
    for count in (2, 3, 2**255):
        with tx_failed():
            env.message_call(c.address, data=selector + _word(32) + _word(count) + _word(32))

    well_formed = selector + _word(32) + _word(1) + _word(32) + _word(3) + b"abc".ljust(32, b"\0")
    assert abi_decode("(uint256)", env.message_call(c.address, data=well_formed)) == (1,)


def test_inf_bytes_array_rejects_head_offset_past_calldata(env, get_contract, tx_failed):
    code = """
@external
def first(xs: DynArray[Bytes[512], INF]) -> Bytes[512]:
    return xs[0]
    """

    c = get_contract(code)
    selector = method_id("first(bytes[])")

    with tx_failed():
        env.message_call(c.address, data=selector + _word(32) + _word(1) + _word(0x2000))


def test_inf_bytes_array_extcall_rejects_count_beyond_returndata(env, get_contract, tx_failed):
    caller_code = """
interface Source:
    def data() -> DynArray[Bytes[512], INF]: view

@external
def get(addr: address) -> DynArray[Bytes[512], INF]:
    return staticcall Source(addr).data()
    """

    caller = get_contract(caller_code)
    target = _deploy_raw_returner(env, _word(32) + _word(5) + _word(32))
    with tx_failed():
        caller.get(target.address)

    target = _deploy_raw_returner(env, abi_encode("(bytes[])", ([b"ok"],)))
    assert caller.get(target.address) == [b"ok"]


def test_inf_nested_dynarray_calldata_roundtrip(get_contract):
    code = """
@external
def echo(xs: DynArray[DynArray[uint256, 3], INF]) -> DynArray[DynArray[uint256, 3], INF]:
    return xs

@external
def total(xs: DynArray[DynArray[uint256, 3], INF]) -> uint256:
    s: uint256 = 0
    for row: DynArray[uint256, 3] in xs:
        for v: uint256 in row:
            s += v
    return s
    """

    c = get_contract(code)
    payload = [[1, 2, 3], [], [4], [5, 6]]
    assert c.echo(payload) == payload
    assert c.echo([]) == []
    assert c.total(payload) == 21


def test_inf_struct_with_bytestring_roundtrip(get_contract):
    code = """
struct Item:
    id: uint256
    name: String[32]
    data: Bytes[64]

@external
def echo(xs: DynArray[Item, INF]) -> DynArray[Item, INF]:
    return xs

@external
def name_of(xs: DynArray[Item, INF], i: uint256) -> String[32]:
    return xs[i].name

@external
def appended(xs: DynArray[Item, INF]) -> DynArray[Item, INF]:
    ys: DynArray[Item, INF] = xs
    ys.append(Item(id=len(xs), name="new", data=b"\\xff"))
    return ys
    """

    c = get_contract(code)
    payload = [(1, "one", b"\x01"), (2, "", b""), (3, "three", b"\x03" * 64)]
    assert c.echo(payload) == payload
    assert c.name_of(payload, 2) == "three"
    assert c.appended(payload) == payload + [(3, "new", b"\xff")]


def test_inf_abi_dynamic_elements_json_abi(compiler_settings):
    code = """
@external
def f(xs: DynArray[Bytes[512], INF]) -> DynArray[String[64], INF]:
    return []
    """

    out = compile_code(code, output_formats=["abi"], settings=compiler_settings)
    (fn,) = out["abi"]
    assert fn["inputs"][0]["type"] == "bytes[]"
    assert fn["outputs"][0]["type"] == "string[]"


# Widening: a bounded (or INF) array whose element type is narrower than the
# INF target's, e.g. DynArray[Bytes[10], 5] -> DynArray[Bytes[512], INF]. The
# element memory strides differ, so these copies must convert layout.


def test_inf_bytes_array_widened_element_assign_and_return(get_contract):
    code = """
@external
def ret(xs: DynArray[Bytes[10], 5]) -> DynArray[Bytes[512], INF]:
    return xs

@external
def assign(xs: DynArray[Bytes[10], 5]) -> DynArray[Bytes[512], INF]:
    ys: DynArray[Bytes[512], INF] = xs
    ys.append(b"appendedappendedappendedappendedappendedappendedappendedappendedappendedappendedappendedappendedappendedappendedappendedappendedappendedappendedappendedappended")
    return ys

@external
def ret_inf(xs: DynArray[Bytes[10], INF]) -> DynArray[Bytes[512], INF]:
    return xs

@external
def assign_inf(xs: DynArray[Bytes[10], INF]) -> DynArray[Bytes[512], INF]:
    ys: DynArray[Bytes[512], INF] = xs
    return ys

@external
def second(xs: DynArray[Bytes[10], 5]) -> Bytes[512]:
    ys: DynArray[Bytes[512], INF] = xs
    return ys[1]
    """

    c = get_contract(code)
    payload = [b"a", b"0123456789", b""]
    assert c.ret(payload) == payload
    assert c.assign(payload) == payload + [b"appended" * 20]
    assert c.ret_inf(payload) == payload
    assert c.assign_inf(payload) == payload
    assert c.second(payload) == b"0123456789"
    assert c.ret([]) == []
    assert c.assign([]) == [b"appended" * 20]


def test_inf_bytes_array_widened_element_internal_calls(get_contract):
    code = """
@internal
def _make() -> DynArray[Bytes[10], 3]:
    return [b"a", b"bb"]

@internal
def _widen(xs: DynArray[Bytes[10], 5]) -> DynArray[Bytes[512], INF]:
    return xs

@internal
def _count(xs: DynArray[Bytes[512], INF]) -> uint256:
    total: uint256 = 0
    for x: Bytes[512] in xs:
        total += len(x)
    return total

@external
def from_internal() -> DynArray[Bytes[512], INF]:
    return self._make()

@external
def via_internal(xs: DynArray[Bytes[10], 5]) -> DynArray[Bytes[512], INF]:
    return self._widen(xs)

@external
def arg_widened(xs: DynArray[Bytes[10], 5]) -> uint256:
    return self._count(xs)
    """

    c = get_contract(code)
    payload = [b"a", b"0123456789", b""]
    assert c.from_internal() == [b"a", b"bb"]
    assert c.via_internal(payload) == payload
    assert c.arg_widened(payload) == 11


def test_inf_bytes_array_widened_element_tuple_returns(get_contract, no_inlining_settings):
    code = """
@internal
def _pair() -> (uint256, DynArray[Bytes[10], 3]):
    return 7, [b"a", b"bb"]

@internal
def _pair_inf() -> (uint256, DynArray[Bytes[512], INF]):
    return self._pair()

@internal
def _pair_inf10() -> (uint256, DynArray[Bytes[10], INF]):
    return self._pair()

@internal
def _pair_inf_widen() -> (uint256, DynArray[Bytes[512], INF]):
    return self._pair_inf10()

@external
def pair() -> (uint256, DynArray[Bytes[512], INF]):
    return self._pair()

@external
def pair_via_inf() -> (uint256, DynArray[Bytes[512], INF]):
    return self._pair_inf()

@external
def pair_frame_widen_internal() -> (uint256, DynArray[Bytes[512], INF]):
    return self._pair_inf_widen()

@external
def pair_frame_widen_external() -> (uint256, DynArray[Bytes[512], INF]):
    return self._pair_inf10()

@external
def literal(xs: DynArray[Bytes[10], 5]) -> (uint256, DynArray[Bytes[512], INF]):
    return len(xs), xs
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.pair() == (7, [b"a", b"bb"])
    assert c.pair_via_inf() == (7, [b"a", b"bb"])
    assert c.pair_frame_widen_internal() == (7, [b"a", b"bb"])
    assert c.pair_frame_widen_external() == (7, [b"a", b"bb"])
    assert c.literal([b"x", b"yy"]) == (2, [b"x", b"yy"])


def test_inf_bytes_array_widened_element_extcall_and_event(env, get_contract):
    target_code = """
@external
def take(xs: DynArray[Bytes[512], INF]) -> DynArray[Bytes[512], INF]:
    return xs
    """

    caller_code = """
event E:
    xs: DynArray[Bytes[512], INF]

interface Target:
    def take(xs: DynArray[Bytes[512], INF]) -> DynArray[Bytes[512], INF]: nonpayable

@external
def call(addr: address, xs: DynArray[Bytes[10], 5]) -> DynArray[Bytes[512], INF]:
    return extcall Target(addr).take(xs)

@external
def emit_event(xs: DynArray[Bytes[10], 5]):
    log E(xs=xs)

@external
def enc(xs: DynArray[Bytes[10], 5]) -> Bytes[INF]:
    ys: DynArray[Bytes[512], INF] = xs
    return abi_encode(ys)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    payload = [b"a", b"0123456789", b""]
    assert caller.call(target.address, payload) == payload
    caller.emit_event(payload)
    assert env.get_logs(caller, raw=True)[0][1] == abi_encode("(bytes[])", (payload,))
    assert caller.enc(payload) == abi_encode("(bytes[])", (payload,))


def test_inf_nested_dynarray_widened_element(get_contract):
    code = """
@external
def widen(xs: DynArray[DynArray[uint256, 2], 3]) -> DynArray[DynArray[uint256, 3], INF]:
    ys: DynArray[DynArray[uint256, 3], INF] = xs
    ys.append([7, 8, 9])
    return ys

@external
def ret(xs: DynArray[DynArray[uint256, 2], 3]) -> DynArray[DynArray[uint256, 3], INF]:
    return xs
    """

    c = get_contract(code)
    payload = [[1, 2], [], [3]]
    assert c.widen(payload) == payload + [[7, 8, 9]]
    assert c.ret(payload) == payload
