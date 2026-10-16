import pytest
from test_inf_abi_dynamic_elements_adversarial import _word

from tests.evm_backends.abi import abi_encode
from vyper.utils import method_id


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


def _bytes_payload(n):
    return [bytes([(i * 7) % 256]) * (i % 64) for i in range(n)]


def _string_payload(n):
    return ["".join(chr(97 + (i + j) % 26) for j in range(i % 64)) for i in range(n)]


_ELEMENT_CASES = [("Bytes[512]", _bytes_payload), ("String[64]", _string_payload)]


@pytest.mark.parametrize("n", [0, 1, 3, 300])
@pytest.mark.parametrize(("elem_t", "make_payload"), _ELEMENT_CASES)
def test_inf_abi_dynamic_elements_calldata_arg(get_contract, elem_t, make_payload, n):
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


@pytest.mark.parametrize(("elem_t", "make_payload"), _ELEMENT_CASES)
def test_inf_abi_dynamic_elements_return_from_calldata(get_contract, elem_t, make_payload):
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
