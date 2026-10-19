import pytest
from eth_abi import decode as eth_abi_decode
from eth_abi import encode as eth_abi_encode

from tests.utils import deploy_raw_returner
from vyper.compiler import compile_code
from vyper.compiler.settings import Settings
from vyper.exceptions import StructureException
from vyper.utils import method_id


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


VALUES = [b"ab", b"", b"c" * 70, b"d" * 33]
NESTED = [VALUES, [], [b"zz"]]


def test_echo_len_index(get_contract):
    code = """
@external
def echo(xs: DynArray[Bytes[INF], INF]) -> DynArray[Bytes[INF], INF]:
    return xs

@external
def n(xs: DynArray[Bytes[INF], INF]) -> uint256:
    return len(xs)

@external
def elem(xs: DynArray[Bytes[INF], INF], i: uint256) -> Bytes[INF]:
    return xs[i]

@external
def elem_len(xs: DynArray[Bytes[INF], INF], i: uint256) -> uint256:
    # the element is a pointer cell; reading the cell as the value would
    # return the payload address here instead of the length
    return len(xs[i])
    """
    c = get_contract(code)
    assert c.echo(VALUES) == VALUES
    assert c.echo([]) == []
    assert c.n(VALUES) == 4
    for i, v in enumerate(VALUES):
        assert c.elem(VALUES, i) == v
        assert c.elem_len(VALUES, i) == len(v)


def test_index_out_of_bounds_reverts(get_contract, tx_failed):
    code = """
@external
def elem(xs: DynArray[Bytes[INF], INF], i: uint256) -> Bytes[INF]:
    return xs[i]
    """
    c = get_contract(code)
    with tx_failed():
        c.elem(VALUES, 4)
    with tx_failed():
        c.elem([], 0)


def test_nested_and_bounded_outer(get_contract):
    code = """
@external
def echo2(xs: DynArray[DynArray[Bytes[INF], INF], INF]) -> DynArray[DynArray[Bytes[INF], INF], INF]:
    return xs

@external
def inner(xs: DynArray[DynArray[Bytes[INF], INF], INF], i: uint256, j: uint256) -> Bytes[INF]:
    return xs[i][j]

@external
def echo5(xs: DynArray[Bytes[INF], 5]) -> DynArray[Bytes[INF], 5]:
    return xs

@external
def ints(xs: DynArray[DynArray[uint256, INF], INF], i: uint256, j: uint256) -> uint256:
    return xs[i][j]
    """
    c = get_contract(code)
    assert c.echo2(NESTED) == NESTED
    assert c.inner(NESTED, 0, 2) == b"c" * 70
    assert c.inner(NESTED, 2, 0) == b"zz"
    assert c.echo5(VALUES[:3]) == VALUES[:3]
    assert c.ints([[1, 2], [], [3]], 2, 0) == 3


def test_bounded_outer_count_cap(get_contract, env, tx_failed):
    code = """
@external
def echo5(xs: DynArray[Bytes[INF], 5]) -> DynArray[Bytes[INF], 5]:
    return xs
    """
    c = get_contract(code)
    with tx_failed():
        c.echo5([b"a"] * 6)


def test_internal_calls_abi_widening_empty_event(get_contract, get_logs):
    code = """
event E:
    xs: DynArray[Bytes[INF], INF]

@internal
def _id(xs: DynArray[Bytes[INF], INF]) -> DynArray[Bytes[INF], INF]:
    return xs

@internal
def _first(xs: DynArray[Bytes[INF], INF]) -> Bytes[INF]:
    return xs[0]

@external
def via_internal(xs: DynArray[Bytes[INF], INF]) -> DynArray[Bytes[INF], INF]:
    return self._id(xs)

@external
def first_via_internal(xs: DynArray[Bytes[INF], INF]) -> Bytes[INF]:
    return self._first(xs)

@external
def roundtrip(data: Bytes[INF]) -> Bytes[INF]:
    xs: DynArray[Bytes[INF], INF] = abi_decode(data, DynArray[Bytes[INF], INF])
    return abi_encode(xs)

@external
def widen(xs: DynArray[Bytes[10], 3]) -> DynArray[Bytes[INF], INF]:
    # inline bounded elements are copied into their own payloads
    ys: DynArray[Bytes[INF], INF] = xs
    return ys

@external
def empties() -> DynArray[Bytes[INF], INF]:
    return empty(DynArray[Bytes[INF], INF])

@external
def emit(xs: DynArray[Bytes[INF], INF]):
    log E(xs=xs)
    """
    c = get_contract(code)
    assert c.via_internal(VALUES) == VALUES
    assert c.first_via_internal(VALUES) == b"ab"
    encoded = eth_abi_encode(["bytes[]"], [VALUES])
    assert c.roundtrip(encoded) == encoded
    assert c.widen([b"a", b"0123456789", b""]) == [b"a", b"0123456789", b""]
    assert c.empties() == []
    c.emit(VALUES)
    (log,) = get_logs(c, "E")
    assert log.args.xs == VALUES


def test_nested_arrays_of_unbounded_structs(get_contract):
    # a bounded array of pointer-cell structs is an inline element (its stride
    # is static); the walker that packs internal returns recurses into it
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@internal
def _id(xs: DynArray[DynArray[Batch, 3], 2]) -> DynArray[DynArray[Batch, 3], 2]:
    return xs

@external
def echo(xs: DynArray[DynArray[Batch, 3], 2]) -> DynArray[DynArray[Batch, 3], 2]:
    return xs

@external
def via_internal(xs: DynArray[DynArray[Batch, 3], 2]) -> DynArray[DynArray[Batch, 3], 2]:
    return self._id(xs)

@external
def inner_len(xs: DynArray[DynArray[Batch, 3], 2], i: uint256, j: uint256) -> uint256:
    return len(xs[i][j].values)

@external
def echo_inf(xs: DynArray[DynArray[Batch, INF], INF]) -> DynArray[DynArray[Batch, INF], INF]:
    return xs
    """
    c = get_contract(code)
    owner = "0x" + "11" * 20
    xs = [[(owner, [1, 2, 3]), (owner, [])], [(owner, [9])]]
    assert c.echo(xs) == xs
    assert c.inner_len(xs, 0, 0) == 3
    assert c.inner_len(xs, 1, 0) == 1
    assert c.via_internal(xs) == xs
    assert c.echo_inf(xs) == xs


def test_staticcall_return(get_contract, env):
    code = """
interface I:
    def g() -> DynArray[Bytes[INF], INF]: view

@external
def f(a: address) -> DynArray[Bytes[INF], INF]:
    return staticcall I(a).g()
    """
    c = get_contract(code)
    returner = deploy_raw_returner(env, eth_abi_encode(["bytes[]"], [VALUES]))
    assert c.f(returner.address) == VALUES


# --- malformed and adversarial input ----------------------------------------

ADV_CODE = """
@external
def echo(xs: DynArray[Bytes[INF], INF]) -> DynArray[Bytes[INF], INF]:
    return xs

@external
def total(xs: DynArray[Bytes[INF], INF]) -> uint256:
    acc: uint256 = 0
    for i: uint256 in range(len(xs), bound=max_value(uint256)):
        acc += len(xs[i])
    return acc
"""


def _call(env, c, name, payload):
    return env.message_call(c.address, data=method_id(name) + payload)


def _bytes_array_calldata(count, offsets, tail):
    # [offset to array][count][element offsets...][tail]
    head = (32).to_bytes(32, "big") + count.to_bytes(32, "big")
    head += b"".join(o.to_bytes(32, "big") for o in offsets)
    return head + tail


def test_aliased_heads_decode_each_element(get_contract, env):
    # the ABI allows every element offset to point at the same tail; each
    # element is decoded into its own payload, so n elements sharing one
    # m-word tail cost O(n*m) memory (see `decode_unbounded_sequence_to_scratch`)
    c = get_contract(ADV_CODE)
    n = 16
    tail = (40).to_bytes(32, "big") + b"x" * 40 + b"\x00" * 24
    data = _bytes_array_calldata(n, [32 * n] * n, tail)
    (decoded,) = eth_abi_decode(["bytes[]"], _call(env, c, "echo(bytes[])", data))
    assert list(decoded) == [b"x" * 40] * n
    assert int.from_bytes(_call(env, c, "total(bytes[])", data), "big") == 40 * n


def test_count_beyond_head_area_reverts(get_contract, env, tx_failed):
    c = get_contract(ADV_CODE)
    tail = (1).to_bytes(32, "big") + b"y" + b"\x00" * 31
    data = _bytes_array_calldata(3, [32 * 3] * 3, tail)
    bad = data[:32] + (1000).to_bytes(32, "big") + data[64:]
    with tx_failed():
        _call(env, c, "echo(bytes[])", bad)


def test_truncated_tail_reverts(get_contract, env, tx_failed):
    c = get_contract(ADV_CODE)
    tail = (100).to_bytes(32, "big") + b"z" * 10
    with tx_failed():
        _call(env, c, "echo(bytes[])", _bytes_array_calldata(1, [32], tail))


def test_wrapped_offset_reverts(get_contract, env, tx_failed):
    c = get_contract(ADV_CODE)
    tail = (1).to_bytes(32, "big") + b"q" + b"\x00" * 31
    with tx_failed():
        _call(env, c, "echo(bytes[])", _bytes_array_calldata(1, [2**256 - 32], tail))


# --- what stays rejected ------------------------------------------------------

REJECTED = [
    (
        """
@external
def f(xs: DynArray[Bytes[INF], INF]):
    ys: DynArray[Bytes[INF], INF] = xs
    ys[0] = b"a"
        """,
        "Cannot modify an element of a DynArray with unbounded element types",
    ),
    (
        """
@external
def f(xs: DynArray[DynArray[uint256, INF], INF]):
    ys: DynArray[DynArray[uint256, INF], INF] = xs
    ys[0][0] = 1
        """,
        "Cannot modify an element of a DynArray with unbounded element types",
    ),
    (
        """
@external
def f(xs: DynArray[Bytes[INF], INF]):
    ys: DynArray[Bytes[INF], INF] = xs
    ys.append(b"a")
        """,
        "append() is not supported on a DynArray with unbounded element types",
    ),
    (
        """
@external
def f(xs: DynArray[Bytes[INF], INF]) -> Bytes[INF]:
    ys: DynArray[Bytes[INF], INF] = xs
    return ys.pop()
        """,
        "pop() is not supported on a DynArray with unbounded element types",
    ),
    (
        """
@external
def f(xs: DynArray[Bytes[INF], INF]) -> uint256:
    n: uint256 = 0
    for x: Bytes[INF] in xs:
        n += len(x)
    return n
        """,
        "Cannot iterate over a DynArray with unbounded element types",
    ),
    (
        """
@external
def f() -> uint256:
    ys: DynArray[Bytes[INF], INF] = [b"a"]
    return len(ys)
        """,
        "List literals cannot have unbounded element types",
    ),
    (
        """
@external
def f(xs: DynArray[Bytes[INF], INF]) -> (uint256, DynArray[Bytes[INF], INF]):
    return 1, xs
        """,
        "Function returns cannot contain unbounded sequence types inside aggregate types",
    ),
    (
        """
interface I:
    def foo(xs: DynArray[Bytes[...], 5]): nonpayable

@external
def f(a: address):
    extcall I(a).foo([])
        """,
        "DynArray element types cannot contain unbounded sequence types",
    ),
]


@pytest.mark.parametrize("code,message", REJECTED)
def test_rejected(code, message):
    with pytest.raises(StructureException) as e:
        compile_code(code, settings=Settings(experimental_codegen=True))
    assert e.value.message == message
