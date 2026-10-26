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


def test_widened_internal_return(get_contract):
    # the packer walks the declared layout, where an element is a pointer
    # cell; a source with inline elements has to be laid out that way first,
    # or inline length words are read as payload pointers
    code = """
@internal
def g3(xs: DynArray[Bytes[10], 3]) -> DynArray[Bytes[INF], 3]:
    return xs

@internal
def g(xs: DynArray[Bytes[10], 3]) -> DynArray[Bytes[INF], INF]:
    return xs

@external
def f3(xs: DynArray[Bytes[10], 3]) -> DynArray[Bytes[INF], 3]:
    return self.g3(xs)

@external
def f(xs: DynArray[Bytes[10], 3]) -> DynArray[Bytes[INF], INF]:
    return self.g(xs)
    """
    c = get_contract(code)
    assert c.f3([b""]) == [b""]
    assert c.f3([b"ab", b"0123456789"]) == [b"ab", b"0123456789"]
    assert c.f([b"ab"]) == [b"ab"]
    assert c.f([]) == []


def test_bounded_outer_copy_arg_and_ternary(get_contract):
    # layout compatibility (`punnable`) must see a pointer cell as a cell, not
    # as an inline value of the same size
    code = """
@internal
def _first_len(xs: DynArray[Bytes[INF], 3]) -> uint256:
    return len(xs[0])

@external
def copy3(xs: DynArray[Bytes[INF], 3]) -> DynArray[Bytes[INF], 3]:
    ys: DynArray[Bytes[INF], 3] = xs
    return ys

@external
def first_len(xs: DynArray[Bytes[INF], 3]) -> uint256:
    return self._first_len(xs)

@external
def pick(
    xs: DynArray[Bytes[INF], INF], ys: DynArray[Bytes[INF], INF], b: bool
) -> DynArray[Bytes[INF], INF]:
    return xs if b else ys
    """
    c = get_contract(code)
    assert c.copy3([b"ab", b""]) == [b"ab", b""]
    assert c.first_len([b"abc"]) == 3
    assert c.pick([b"x"], [b"y"], True) == [b"x"]
    assert c.pick([b"x"], [b"y"], False) == [b"y"]


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


# --- mutation: elements are replaced, never written in place -----------------

VALUES_SHORT = [b"ab", b"", b"c" * 70]


def test_element_store_and_copy_independence(get_contract):
    code = """
@external
def replace(xs: DynArray[Bytes[INF], INF], i: uint256, v: Bytes[INF]) -> DynArray[Bytes[INF], INF]:
    ys: DynArray[Bytes[INF], INF] = xs
    ys[i] = v
    return ys

@external
def copy_then_store(xs: DynArray[Bytes[INF], INF]) -> (Bytes[INF], Bytes[INF]):
    ys: DynArray[Bytes[INF], INF] = xs
    ys[0] = b"zz"
    # the copy and the original hold separate cells; the original is untouched
    return xs[0], ys[0]

@external
def store_from_call(xs: DynArray[Bytes[INF], INF], a: Bytes[INF], b: Bytes[INF]) -> Bytes[INF]:
    ys: DynArray[Bytes[INF], INF] = xs
    ys[1] = concat(a, b)
    return ys[1]

@external
def store_self(xs: DynArray[Bytes[INF], INF]) -> DynArray[Bytes[INF], INF]:
    ys: DynArray[Bytes[INF], INF] = xs
    ys[0] = ys[2]
    ys[2] = b""
    return ys
    """
    c = get_contract(code)
    assert c.replace(VALUES_SHORT, 1, b"new" * 30) == [b"ab", b"new" * 30, b"c" * 70]
    assert c.replace(VALUES_SHORT, 0, b"") == [b"", b"", b"c" * 70]
    assert c.copy_then_store(VALUES_SHORT) == (b"ab", b"zz")
    assert c.store_from_call(VALUES_SHORT, b"x" * 40, b"y" * 40) == b"x" * 40 + b"y" * 40
    assert c.store_self(VALUES_SHORT) == [b"c" * 70, b"", b""]


def test_append_pop(get_contract, env):
    code = """
@external
def build(n: uint256) -> DynArray[Bytes[INF], INF]:
    xs: DynArray[Bytes[INF], INF] = []
    for i: uint256 in range(n, bound=max_value(uint256)):
        xs.append(slice(b"0123456789abcdefghijklmnopqrstuvwxyz", 0, i % 36 + 1))
    return xs

@external
def push_pop(xs: DynArray[Bytes[INF], INF]) -> DynArray[Bytes[INF], INF]:
    ys: DynArray[Bytes[INF], INF] = xs
    ys.append(b"tail")
    ys.append(ys[0])
    ys.pop()
    return ys

@external
def popped(xs: DynArray[Bytes[INF], INF]) -> Bytes[INF]:
    ys: DynArray[Bytes[INF], INF] = xs
    ys.append(b"tail")
    ys.append(ys[0])
    return ys.pop()

@external
def bounded(xs: DynArray[Bytes[INF], 3]) -> DynArray[Bytes[INF], 3]:
    ys: DynArray[Bytes[INF], 3] = xs
    ys.append(b"q")
    ys.pop()
    ys.append(b"rrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr")
    return ys

@external
def bounded_pop(xs: DynArray[Bytes[INF], 3]) -> Bytes[INF]:
    ys: DynArray[Bytes[INF], 3] = xs
    ys.append(b"q")
    return ys.pop()

@external
def from_calls(t: address) -> DynArray[Bytes[INF], INF]:
    xs: DynArray[Bytes[INF], INF] = []
    for i: uint256 in range(3):
        xs.append(raw_call(t, b"", max_outsize=INF, is_static_call=True))
    return xs
    """
    c = get_contract(code)
    for n in (0, 1, 2, 5, 40):
        expected = [b"0123456789abcdefghijklmnopqrstuvwxyz"[: i % 36 + 1] for i in range(n)]
        assert c.build(n) == expected
    assert c.push_pop(VALUES_SHORT) == VALUES_SHORT + [b"tail"]
    assert c.popped(VALUES_SHORT) == b"ab"
    assert c.bounded([b"a", b"b"]) == [b"a", b"b", b"r" * 40]
    assert c.bounded_pop([b"a", b"b"]) == b"q"
    ret = deploy_raw_returner(env, b"\x11" * 40)
    assert c.from_calls(ret.address) == [b"\x11" * 40] * 3


def test_store_converted_value(get_contract, env):
    # unlike an external call result, `convert(s, Bytes[INF])` is `s`'s own
    # buffer, so the element must get a copy which survives writes to `s`
    code = """
interface I:
    def g() -> Bytes[INF]: view

@external
def append_converted() -> DynArray[Bytes[INF], INF]:
    s: String[10] = "one"
    xs: DynArray[Bytes[INF], INF] = []
    xs.append(convert(s, Bytes[INF]))
    s = "two"
    return xs

@external
def store_converted() -> DynArray[Bytes[INF], INF]:
    s: String[10] = "one"
    xs: DynArray[Bytes[INF], INF] = [b"z"]
    xs[0] = convert(s, Bytes[INF])
    s = "two"
    return xs

@external
def literal_converted() -> DynArray[Bytes[INF], INF]:
    s: String[10] = "one"
    xs: DynArray[Bytes[INF], INF] = [convert(s, Bytes[INF])]
    s = "two"
    return xs

@external
def from_staticcalls(a: address) -> DynArray[Bytes[INF], INF]:
    xs: DynArray[Bytes[INF], INF] = [b"z", staticcall I(a).g()]
    xs.append(staticcall I(a).g())
    xs[0] = staticcall I(a).g()
    return xs
    """
    c = get_contract(code)
    assert c.append_converted() == [b"one"]
    assert c.store_converted() == [b"one"]
    assert c.literal_converted() == [b"one"]
    ret = deploy_raw_returner(env, eth_abi_encode(["bytes"], [b"\x22" * 40]))
    assert c.from_staticcalls(ret.address) == [b"\x22" * 40] * 3


def test_tuple_unpack_into_elements(get_contract):
    code = """
@internal
def pair() -> (Bytes[INF], Bytes[INF]):
    return b"a", b"bb"

@internal
def pair5() -> (Bytes[5], Bytes[5]):
    return b"a", b"bb"

@internal
def with_word() -> (Bytes[INF], uint256):
    return b"ccc", 7

@internal
def swapped(a: Bytes[INF], b: Bytes[INF]) -> (Bytes[INF], Bytes[INF]):
    return b, a

@external
def unbounded_pair() -> DynArray[Bytes[INF], INF]:
    xs: DynArray[Bytes[INF], INF] = [b"", b""]
    xs[0], xs[1] = self.pair()
    return xs

@external
def bounded_pair() -> DynArray[Bytes[INF], INF]:
    xs: DynArray[Bytes[INF], INF] = [b"", b""]
    xs[0], xs[1] = self.pair5()
    return xs

@external
def element_and_word() -> (Bytes[INF], uint256):
    xs: DynArray[Bytes[INF], INF] = [b""]
    n: uint256 = 0
    xs[0], n = self.with_word()
    return xs[0], n

@external
def local_and_element() -> (Bytes[INF], Bytes[INF], Bytes[INF]):
    a: Bytes[INF] = b"z"
    xs: DynArray[Bytes[INF], INF] = [b"x", b"y"]
    a, xs[1] = self.pair()
    return a, xs[0], xs[1]

@external
def swap(xs: DynArray[Bytes[INF], INF]) -> DynArray[Bytes[INF], INF]:
    ys: DynArray[Bytes[INF], INF] = xs
    ys[0], ys[1] = self.swapped(ys[0], ys[1])
    return ys
    """
    c = get_contract(code)
    assert c.unbounded_pair() == [b"a", b"bb"]
    assert c.bounded_pair() == [b"a", b"bb"]
    assert c.element_and_word() == (b"ccc", 7)
    assert c.local_and_element() == (b"a", b"x", b"bb")
    assert c.swap(VALUES_SHORT) == [b"", b"ab", b"c" * 70]


def test_iteration_and_literals(get_contract):
    code = """
@external
def total(xs: DynArray[Bytes[INF], INF]) -> uint256:
    n: uint256 = 0
    for x: Bytes[INF] in xs:
        n += len(x)
    return n

@external
def nested_total(xs: DynArray[DynArray[Bytes[INF], INF], INF]) -> uint256:
    n: uint256 = 0
    for row: DynArray[Bytes[INF], INF] in xs:
        for x: Bytes[INF] in row:
            n += len(x)
    return n

@external
def literal() -> DynArray[Bytes[INF], INF]:
    return [b"a", b"", b"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]

@external
def literal5() -> DynArray[Bytes[INF], 5]:
    return [b"x", b"yy"]

@external
def write_other_while_iterating(xs: DynArray[Bytes[INF], INF]) -> DynArray[Bytes[INF], INF]:
    ys: DynArray[Bytes[INF], INF] = xs
    for x: Bytes[INF] in xs:
        ys[0] = x
    return ys
    """
    c = get_contract(code)
    assert c.total(VALUES_SHORT) == 72
    assert c.nested_total([VALUES_SHORT, [], [b"zz"]]) == 74
    assert c.literal() == [b"a", b"", b"bb" * 20]
    assert c.literal5() == [b"x", b"yy"]
    assert c.write_other_while_iterating(VALUES_SHORT) == [b"c" * 70, b"", b"c" * 70]


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
def f(xs: DynArray[DynArray[uint256, INF], INF]):
    ys: DynArray[DynArray[uint256, INF], INF] = xs
    ys[0][0] = 1
        """,
        "Cannot modify an unbounded element in place",
    ),
    (
        """
@external
def f(xs: DynArray[DynArray[uint256, INF], INF]):
    ys: DynArray[DynArray[uint256, INF], INF] = xs
    ys[0].append(1)
        """,
        "Cannot modify an unbounded element in place",
    ),
    (
        """
@external
def f(xs: DynArray[DynArray[Bytes[INF], INF], INF]):
    ys: DynArray[DynArray[Bytes[INF], INF], INF] = xs
    ys[0][1] = b"a"
        """,
        "Cannot modify an unbounded element in place",
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
