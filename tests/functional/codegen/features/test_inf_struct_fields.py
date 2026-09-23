import pytest
from eth_abi import decode as eth_abi_decode
from eth_abi import encode as eth_abi_encode

from vyper.compiler import compile_code
from vyper.utils import method_id


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


LENGTHS = [0, 1, 3, 40]


@pytest.mark.parametrize("n", LENGTHS)
def test_struct_inf_field_echo(get_contract, n):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def echo(b: Batch) -> Batch:
    return b
    """

    c = get_contract(code)
    owner = "0x" + "11" * 20
    values = list(range(1, n + 1))
    assert c.echo((owner, values)) == (owner, values)


@pytest.mark.parametrize("n", LENGTHS)
def test_struct_inf_field_len(get_contract, n):
    # the member is a pointer cell; a lowering that read the cell as the value
    # would return the payload address here instead of the length
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def size(b: Batch) -> uint256:
    return len(b.values)
    """

    c = get_contract(code)
    assert c.size(("0x" + "22" * 20, list(range(n)))) == n


@pytest.mark.parametrize("n", LENGTHS)
def test_struct_inf_field_iterate(get_contract, n):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def total(b: Batch) -> uint256:
    acc: uint256 = 0
    for v: uint256 in b.values:
        acc += v
    return acc
    """

    c = get_contract(code)
    values = list(range(1, n + 1))
    assert c.total(("0x" + "33" * 20, values)) == sum(values)


def test_struct_inf_field_index(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def at(b: Batch, i: uint256) -> uint256:
    return b.values[i]
    """

    c = get_contract(code)
    values = [7, 8, 9]
    b = ("0x" + "44" * 20, values)
    for i, expected in enumerate(values):
        assert c.at(b, i) == expected


def test_bounded_members_around_inf_member(get_contract):
    # members before and after the pointer cell must keep their own offsets
    code = """
struct Mixed:
    head: uint256
    values: DynArray[uint256, INF]
    tail: uint256
    flags: bool[3]

@external
def read(m: Mixed) -> (uint256, uint256, uint256, bool[3]):
    return m.head, len(m.values), m.tail, m.flags
    """

    c = get_contract(code)
    value = (11, [1, 2, 3, 4, 5], 22, [True, False, True])
    assert c.read(value) == (11, 5, 22, [True, False, True])


def test_two_inf_members(get_contract):
    code = """
struct Pair:
    left: DynArray[uint256, INF]
    right: DynArray[uint256, INF]

@external
def echo(p: Pair) -> Pair:
    return p

@external
def lengths(p: Pair) -> (uint256, uint256):
    return len(p.left), len(p.right)
    """

    c = get_contract(code)
    value = ([1, 2, 3], [4, 5])
    assert c.echo(value) == value
    assert c.lengths(value) == (3, 2)


@pytest.mark.parametrize("n", [0, 1, 32, 100])
def test_bytes_inf_member(get_contract, n):
    code = """
struct Msg:
    kind: uint256
    payload: Bytes[INF]

@external
def echo(m: Msg) -> Msg:
    return m

@external
def size(m: Msg) -> uint256:
    return len(m.payload)
    """

    c = get_contract(code)
    value = (7, bytes(range(256))[:n])
    assert c.echo(value) == value
    assert c.size(value) == n


def test_string_inf_member(get_contract):
    code = """
struct Named:
    id: uint256
    name: String[INF]

@external
def echo(n: Named) -> Named:
    return n
    """

    c = get_contract(code)
    value = (3, "hello unbounded world")
    assert c.echo(value) == value


def test_nested_struct_inf_member(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

struct Outer:
    tag: uint256
    batch: Batch

@external
def echo(o: Outer) -> Outer:
    return o

@external
def size(o: Outer) -> uint256:
    return len(o.batch.values)
    """

    c = get_contract(code)
    value = (9, ("0x" + "55" * 20, [1, 2, 3, 4]))
    assert c.echo(value) == value
    assert c.size(value) == 4


def test_internal_call_with_inf_struct_arg(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@internal
def _total(b: Batch) -> uint256:
    acc: uint256 = 0
    for v: uint256 in b.values:
        acc += v
    return acc

@external
def total(b: Batch) -> uint256:
    return self._total(b)
    """

    c = get_contract(code)
    assert c.total(("0x" + "66" * 20, [10, 20, 30])) == 60


def test_internal_call_returning_inf_struct(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@internal
def _pass(b: Batch) -> Batch:
    return b

@external
def echo(b: Batch) -> Batch:
    return self._pass(b)
    """

    c = get_contract(code)
    value = ("0x" + "77" * 20, [5, 6, 7])
    assert c.echo(value) == value


def test_local_copy_of_inf_struct(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def echo(b: Batch) -> Batch:
    copy: Batch = b
    return copy
    """

    c = get_contract(code)
    value = ("0x" + "88" * 20, [1, 2, 3])
    assert c.echo(value) == value


def test_struct_constructor_with_inf_field(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def build(owner: address, values: DynArray[uint256, INF]) -> Batch:
    return Batch(owner=owner, values=values)
    """

    c = get_contract(code)
    owner = "0x" + "99" * 20
    assert c.build(owner, [4, 5, 6]) == (owner, [4, 5, 6])


def test_struct_constructor_source_is_copied(get_contract):
    # the struct owns its members, so appending to the initializer afterwards
    # must not be visible through the struct, including when the append has
    # room to write into the buffer the initializer already holds
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def build() -> Batch:
    src: DynArray[uint256, INF] = [1, 2, 3]
    for i: uint256 in range(6):
        src.append(100 + i)
    b: Batch = Batch(owner=self, values=src)
    for i: uint256 in range(6):
        src.append(200 + i)
    return b
    """

    c = get_contract(code)
    _owner, values = c.build()
    assert values == [1, 2, 3, 100, 101, 102, 103, 104, 105]


def test_dynarray_of_structs_with_inf_field(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def count(bs: DynArray[Batch, INF]) -> uint256:
    return len(bs)

@external
def size(bs: DynArray[Batch, INF], i: uint256) -> uint256:
    return len(bs[i].values)

@external
def at(bs: DynArray[Batch, INF], i: uint256, j: uint256) -> uint256:
    return bs[i].values[j]

@external
def owner(bs: DynArray[Batch, INF], i: uint256) -> address:
    return bs[i].owner
    """

    c = get_contract(code)
    a = "0x" + "aa" * 20
    b = "0x" + "bb" * 20
    batches = [(a, [1, 2]), (b, [3, 4, 5])]
    assert c.count(batches) == 2
    assert c.size(batches, 0) == 2
    assert c.size(batches, 1) == 3
    assert c.at(batches, 1, 2) == 5
    assert c.owner(batches, 1).lower() == b


def test_bounded_dynarray_of_structs_with_inf_field(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def size(bs: DynArray[Batch, 4], i: uint256) -> uint256:
    return len(bs[i].values)
    """

    c = get_contract(code)
    a = "0x" + "cc" * 20
    batches = [(a, [1]), (a, [2, 3, 4])]
    assert c.size(batches, 0) == 1
    assert c.size(batches, 1) == 3


@pytest.mark.parametrize("n", LENGTHS)
def test_abi_roundtrip_matches_eth_abi(get_contract, env, n):
    # the struct's external ABI is the plain tuple, unchanged by the
    # pointer-cell memory representation
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def echo(b: Batch) -> Batch:
    return b
    """

    out = compile_code(code, output_formats=["abi"])
    (fn,) = [item for item in out["abi"] if item.get("name") == "echo"]
    assert fn["inputs"][0]["type"] == "tuple"
    assert [comp["type"] for comp in fn["inputs"][0]["components"]] == ["address", "uint256[]"]

    c = get_contract(code)
    owner = "0x" + "12" * 20
    values = list(range(100, 100 + n))

    calldata = method_id("echo((address,uint256[]))") + eth_abi_encode(
        ["(address,uint256[])"], [(owner, values)]
    )

    output = env.message_call(c.address, data=calldata)
    decoded_owner, decoded_values = eth_abi_decode(["(address,uint256[])"], output)[0]
    assert decoded_owner == owner.lower()
    assert list(decoded_values) == values


def test_for_over_dynarray_of_structs(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def total(bs: DynArray[Batch, INF]) -> uint256:
    acc: uint256 = 0
    for b: Batch in bs:
        for v: uint256 in b.values:
            acc += v
    return acc
    """

    c = get_contract(code)
    a = "0x" + "dd" * 20
    assert c.total([(a, [1, 2]), (a, [3, 4, 5])]) == 15


def test_struct_reassignment(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def pick(b: Batch, c: Batch) -> Batch:
    d: Batch = b
    d = c
    return d
    """

    c = get_contract(code)
    x = ("0x" + "01" * 20, [1, 2, 3])
    y = ("0x" + "02" * 20, [9])
    assert c.pick(x, y) == y


def test_struct_ternary(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def pick(b: Batch, c: Batch, take_first: bool) -> uint256:
    d: Batch = b if take_first else c
    return len(d.values)
    """

    c = get_contract(code)
    x = ("0x" + "03" * 20, [1, 2, 3])
    y = ("0x" + "04" * 20, [9])
    assert c.pick(x, y, True) == 3
    assert c.pick(x, y, False) == 1


def test_constructor_arg_with_inf_struct_field(get_contract, env):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

count: public(uint256)
first: public(uint256)
owner: public(address)

@deploy
def __init__(b: Batch):
    self.count = len(b.values)
    self.first = b.values[0]
    self.owner = b.owner
    """

    owner = "0x" + "05" * 20
    c = get_contract(code, (owner, [42, 43, 44]))
    assert c.count() == 3
    assert c.first() == 42
    assert c.owner().lower() == owner


def test_oversized_member_length_reverts(get_contract, env, tx_failed):
    # the member has no length cap of its own, so the decoder has to bound the
    # claimed length by the readable calldata instead of expanding memory for it
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@external
def size(b: Batch) -> uint256:
    return len(b.values)
    """

    c = get_contract(code)
    calldata = (
        method_id("size((address,uint256[]))")
        + (32).to_bytes(32, "big")  # offset of the struct
        + (0).to_bytes(32, "big")  # owner
        + (64).to_bytes(32, "big")  # offset of `values` within the struct
        + (2**32).to_bytes(32, "big")  # claimed element count, with no payload
    )

    with tx_failed():
        env.message_call(c.address, data=calldata)


def test_internal_call_with_list_literal_of_inf_structs(get_contract):
    code = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]

@internal
def _total(bs: DynArray[Batch, 3]) -> uint256:
    acc: uint256 = len(bs) * 1000
    for b: Batch in bs:
        for v: uint256 in b.values:
            acc += v
    return acc

@external
def one(b: Batch) -> uint256:
    return self._total([b])

@external
def two(b: Batch, c: Batch) -> uint256:
    return self._total([b, c])

@external
def constructed() -> uint256:
    return self._total([Batch(owner=self, values=[1, 2]), Batch(owner=self, values=[3])])

@external
def source_after_call(b: Batch) -> uint256:
    r: uint256 = self._total([b])
    return r + len(b.values)
    """

    c = get_contract(code)
    a = "0x" + "99" * 20
    assert c.one((a, [10, 20, 30])) == 1060
    assert c.one((a, [])) == 1000
    assert c.two((a, [10, 20, 30]), (a, [5])) == 2065
    assert c.constructed() == 2006
    assert c.source_after_call((a, [10, 20, 30])) == 1063


# An internal function returning a struct with INF members copies its payloads
# into the caller's frame, so they outlive the callee frame. Each producer is
# called twice from one external function: a payload left in the callee frame
# is overwritten by the second call, and a single call site is inlined at
# -O gas, which would hide that.
def test_internal_return_survives_second_call(get_contract):
    code = """
struct S:
    a: DynArray[uint256, INF]
    n: uint256

@internal
def g(x: uint256) -> S:
    return S(a=[x, x + 1], n=x)

@external
def f() -> (uint256, uint256, uint256):
    first: S = self.g(1)
    second: S = self.g(99)
    return first.a[0], first.a[1], first.n
    """

    c = get_contract(code)
    assert c.f() == (1, 2, 1)


def test_internal_return_rebuilt_from_arg(get_contract):
    code = """
struct S:
    a: DynArray[uint256, INF]
    n: uint256

@internal
def rebuild(s: S) -> S:
    return S(a=s.a, n=s.n)

@external
def f() -> (uint256, uint256, uint256):
    first: S = self.rebuild(S(a=[1, 2], n=7))
    second: S = self.rebuild(S(a=[99, 100], n=8))
    return first.a[0], first.a[1], first.n
    """

    c = get_contract(code)
    assert c.f() == (1, 2, 7)


def test_internal_return_nested_struct(get_contract):
    code = """
struct S:
    a: DynArray[uint256, INF]
    n: uint256

struct Outer:
    k: uint256
    b: S

@internal
def g(x: uint256) -> Outer:
    return Outer(k=x, b=S(a=[x, x + 1], n=x))

@external
def f() -> (uint256, uint256, uint256, uint256):
    first: Outer = self.g(1)
    second: Outer = self.g(99)
    return first.k, first.b.a[0], first.b.a[1], first.b.n
    """

    c = get_contract(code)
    assert c.f() == (1, 1, 2, 1)


def test_internal_return_then_unrelated_allocation(get_contract):
    code = """
struct S:
    a: DynArray[uint256, INF]
    n: uint256

@internal
def g(x: uint256) -> S:
    return S(a=[x, x + 1], n=x)

@internal
def noise() -> uint256:
    z: DynArray[uint256, INF] = [7, 7, 7, 7]
    return len(z)

@external
def f() -> (uint256, uint256, uint256):
    first: S = self.g(1)
    k: uint256 = self.noise()
    second: S = self.g(k)
    return first.a[0], first.a[1], second.a[0]
    """

    c = get_contract(code)
    assert c.f() == (1, 2, 4)


def test_internal_return_copied_then_second_call(get_contract):
    code = """
struct S:
    a: DynArray[uint256, INF]
    n: uint256

@internal
def g(x: uint256) -> S:
    return S(a=[x, x + 1], n=x)

@external
def f() -> (uint256, uint256, uint256):
    first: S = self.g(1)
    cp: S = first
    second: S = self.g(99)
    return cp.a[0], cp.a[1], cp.n
    """

    c = get_contract(code)
    assert c.f() == (1, 2, 1)


def test_internal_return_with_live_caller_local(get_contract):
    code = """
struct S:
    a: DynArray[uint256, INF]
    n: uint256

@internal
def g(x: uint256) -> S:
    return S(a=[x, x + 1], n=x)

@external
def f() -> (uint256, uint256, uint256, uint256):
    z: DynArray[uint256, INF] = [5, 6, 7]
    first: S = self.g(1)
    second: S = self.g(99)
    return first.a[0], first.a[1], z[0], len(z)
    """

    c = get_contract(code)
    assert c.f() == (1, 2, 5, 3)


def test_internal_return_empty_payload(get_contract):
    code = """
struct S:
    a: DynArray[uint256, INF]
    n: uint256

@internal
def g(xs: DynArray[uint256, INF], n: uint256) -> S:
    return S(a=xs, n=n)

@external
def f() -> (uint256, uint256, uint256, uint256):
    first: S = self.g([], 1)
    second: S = self.g([99, 100], 99)
    return len(first.a), first.n, len(second.a), second.n
    """

    c = get_contract(code)
    assert c.f() == (0, 1, 2, 99)


def test_internal_return_bytestring_members(get_contract):
    code = """
struct Msg:
    payload: Bytes[INF]
    name: String[INF]

@internal
def g(tag: Bytes[4]) -> Msg:
    return Msg(payload=concat(tag, b"-payload"), name="named")

@external
def f() -> (Bytes[INF], String[INF]):
    first: Msg = self.g(b"aaaa")
    second: Msg = self.g(b"zzzz")
    return first.payload, first.name
    """

    c = get_contract(code)
    assert c.f() == (b"aaaa-payload", "named")


def test_internal_return_mixed_members(get_contract):
    code = """
struct Rec:
    values: DynArray[uint256, INF]
    tag: uint256
    data: Bytes[INF]

@internal
def g(x: uint256, tag: Bytes[4]) -> Rec:
    return Rec(values=[x, x + 1, x + 2], tag=x, data=tag)

@external
def f() -> (uint256, uint256, uint256, uint256, Bytes[INF]):
    first: Rec = self.g(1, b"abcd")
    second: Rec = self.g(99, b"wxyz")
    return first.values[0], first.values[2], len(first.values), first.tag, first.data
    """

    c = get_contract(code)
    assert c.f() == (1, 3, 3, 1, b"abcd")


# The returned struct is the callee's argument, whose payload the caller
# staged in its own frame; the second call cannot overwrite it.
def test_internal_return_of_arg(get_contract):
    code = """
struct S:
    a: DynArray[uint256, INF]
    n: uint256

@internal
def ident(s: S) -> S:
    return s

@external
def f(s: S) -> (uint256, uint256, uint256):
    first: S = self.ident(s)
    second: S = self.ident(S(a=[99, 100], n=99))
    return first.a[0], first.a[1], first.n
    """

    c = get_contract(code)
    assert c.f(([1, 2], 3)) == (1, 2, 3)
