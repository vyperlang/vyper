import pytest
from eth_abi import decode as eth_abi_decode
from eth_abi import encode as eth_abi_encode

from tests.evm_backends.abi import abi_decode
from tests.evm_backends.base_env import ExecutionReverted
from tests.utils import deploy_raw_returner, word
from vyper.codegen_venom.module import generate_venom_runtime
from vyper.compiler import compile_code
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import anchor_settings
from vyper.utils import keccak256, method_id


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


# Mutation of an unbounded member. The struct holds a pointer cell for the
# member, and a copied struct shares the member's payload with its source
# until the first write: a member assignment points the cell at a fresh
# payload, and an element store, append or pop first copies a shared payload
# so that no other struct observes the write.

BATCH = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]
"""

OWNER = "0x" + "12" * 20


def test_member_assign_from_local(get_contract):
    code = BATCH + """
@external
def f(b: Batch) -> (address, DynArray[uint256, INF], uint256):
    c: Batch = b
    v: DynArray[uint256, INF] = [7, 8, 9]
    c.values = v
    v.append(10)
    return c.owner, c.values, len(c.values)
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2])) == (OWNER, [7, 8, 9], 3)


def test_member_assign_from_other_member(get_contract):
    code = BATCH + """
@external
def f(b: Batch, d: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
    c: Batch = b
    e: Batch = d
    c.values = e.values
    e.values.append(100)
    return c.values, e.values
    """

    c = get_contract(code)
    other = "0x" + "34" * 20
    assert c.f((OWNER, [1, 2]), (other, [5, 6, 7])) == ([5, 6, 7], [5, 6, 7, 100])


def test_member_assign_from_external_arg_member(get_contract):
    code = BATCH + """
@external
def f(b: Batch, d: Batch) -> Batch:
    c: Batch = b
    c.values = d.values
    return c
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2]), ("0x" + "34" * 20, [5, 6, 7])) == (OWNER, [5, 6, 7])


def test_member_assign_from_literal(get_contract):
    code = BATCH + """
@external
def f(b: Batch) -> (DynArray[uint256, INF], uint256):
    c: Batch = b
    c.values = [7, 8, 9, 10]
    return c.values, len(c.values)
    """

    c = get_contract(code)
    assert c.f((OWNER, [1])) == ([7, 8, 9, 10], 4)


@pytest.mark.parametrize("empty_value", ["[]", "empty(DynArray[uint256, INF])"])
def test_member_assign_empty(get_contract, empty_value):
    code = BATCH + f"""
@external
def f(b: Batch) -> (DynArray[uint256, INF], uint256):
    c: Batch = b
    c.values = {empty_value}
    return c.values, len(c.values)
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == ([], 0)


def test_member_assign_from_internal_call(get_contract):
    code = BATCH + """
@internal
def make(n: uint256) -> DynArray[uint256, INF]:
    xs: DynArray[uint256, INF] = []
    for i: uint256 in range(n, bound=100):
        xs.append(i * 10)
    return xs

@external
def f(b: Batch, n: uint256) -> (DynArray[uint256, INF], uint256):
    c: Batch = b
    c.values = self.make(n)
    return c.values, len(c.values)
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3]), 5) == ([0, 10, 20, 30, 40], 5)
    assert c.f((OWNER, [1, 2, 3]), 0) == ([], 0)


def test_member_assign_to_itself(get_contract):
    code = BATCH + """
@external
def f(b: Batch) -> (DynArray[uint256, INF], uint256):
    c: Batch = b
    c.values = c.values
    c.values.append(4)
    return c.values, len(c.values)
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == ([1, 2, 3, 4], 4)


def test_member_element_store(get_contract):
    code = BATCH + """
@external
def f(b: Batch, i: uint256, x: uint256) -> (DynArray[uint256, INF], uint256):
    c: Batch = b
    c.values[i] = x
    c.values[i] += 1
    return c.values, len(c.values)
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3]), 1, 20) == ([1, 21, 3], 3)
    assert c.f((OWNER, [1, 2, 3]), 2, 0) == ([1, 2, 1], 3)


def test_member_element_store_out_of_bounds_reverts(get_contract, tx_failed):
    code = BATCH + """
@external
def f(b: Batch, i: uint256):
    c: Batch = b
    c.values[i] = 1
    """

    c = get_contract(code)
    with tx_failed():
        c.f((OWNER, [1, 2, 3]), 3)
    with tx_failed():
        c.f((OWNER, []), 0)


def test_member_element_store_from_pop(get_contract):
    code = BATCH + """
@external
def f(b: Batch) -> (DynArray[uint256, INF], uint256):
    c: Batch = b
    c.values[0] = c.values.pop()
    return c.values, len(c.values)
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == ([3, 2], 2)


def test_member_element_store_from_own_element(get_contract):
    code = """
struct Blob:
    tag: uint256
    chunks: DynArray[Bytes[32], INF]

@external
def f(b: Blob, i: uint256, j: uint256) -> (DynArray[Bytes[32], INF], uint256):
    c: Blob = b
    c.chunks[i] = c.chunks[j]
    return c.chunks, len(c.chunks)
    """

    c = get_contract(code)
    chunks = [b"a" * 32, b"bb", b"ccc"]
    assert c.f((1, chunks), 0, 2) == ([b"ccc", b"bb", b"ccc"], 3)
    assert c.f((1, chunks), 2, 0) == ([b"a" * 32, b"bb", b"a" * 32], 3)


def test_member_element_field_store(get_contract):
    code = """
struct Point:
    x: uint256
    y: uint256

struct Path:
    name: String[8]
    points: DynArray[Point, INF]

@external
def f(p: Path, i: uint256) -> Path:
    c: Path = p
    c.points[i].y = 99
    return c
    """

    c = get_contract(code)
    assert c.f(("p", [(1, 2), (3, 4)]), 1) == ("p", [(1, 2), (3, 99)])


def test_member_append_from_empty(get_contract):
    code = BATCH + """
@external
def f(n: uint256) -> (DynArray[uint256, INF], uint256):
    c: Batch = Batch(owner=self, values=[])
    for i: uint256 in range(n, bound=64):
        c.values.append(i)
    return c.values, len(c.values)
    """

    c = get_contract(code)
    for n in [0, 1, 2, 3, 40]:
        assert c.f(n) == (list(range(n)), n)


def test_member_append_own_element(get_contract):
    code = BATCH + """
@external
def f(b: Batch) -> (DynArray[uint256, INF], uint256):
    c: Batch = b
    c.values.append(c.values[0])
    c.values.append(c.values[0])
    return c.values, len(c.values)
    """

    c = get_contract(code)
    assert c.f((OWNER, [7, 8])) == ([7, 8, 7, 7], 4)


def test_member_pop_then_append(get_contract):
    code = BATCH + """
@external
def f(b: Batch) -> (DynArray[uint256, INF], uint256, uint256, uint256):
    c: Batch = b
    first: uint256 = c.values.pop()
    second: uint256 = c.values.pop()
    n: uint256 = len(c.values)
    c.values.append(30)
    return c.values, first, second, n
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2])) == ([30], 2, 1, 0)


def test_member_pop_empty_reverts(get_contract, tx_failed):
    code = BATCH + """
@external
def f(b: Batch) -> uint256:
    c: Batch = b
    return c.values.pop()
    """

    c = get_contract(code)
    assert c.f((OWNER, [5])) == 5
    with tx_failed():
        c.f((OWNER, []))


def test_nested_member_mutation(get_contract):
    code = BATCH + """
struct Outer:
    tag: uint256
    inner: Batch

@external
def assign(o: Outer) -> (uint256, DynArray[uint256, INF], uint256):
    c: Outer = o
    c.inner.values = [7, 8]
    return c.tag, c.inner.values, len(c.inner.values)

@external
def store(o: Outer, i: uint256, x: uint256) -> Outer:
    c: Outer = o
    c.inner.values[i] = x
    c.inner.values[i] += 1
    return c

@external
def append(o: Outer, n: uint256) -> (DynArray[uint256, INF], uint256):
    c: Outer = o
    for i: uint256 in range(n, bound=40):
        c.inner.values.append(i)
    return c.inner.values, len(c.inner.values)

@external
def pop(o: Outer) -> (DynArray[uint256, INF], uint256, uint256):
    c: Outer = o
    x: uint256 = c.inner.values.pop()
    return c.inner.values, x, len(c.inner.values)
    """

    c = get_contract(code)
    o = (9, (OWNER, [1, 2, 3]))
    assert c.assign(o) == (9, [7, 8], 2)
    assert c.store(o, 0, 10) == (9, (OWNER, [11, 2, 3]))
    assert c.append(o, 3) == ([1, 2, 3, 0, 1, 2], 6)
    assert c.append(o, 20) == ([1, 2, 3] + list(range(20)), 23)
    assert c.pop(o) == ([1, 2], 3, 2)


def test_bytestring_member_assign(get_contract):
    code = """
struct Msg:
    payload: Bytes[INF]
    name: String[INF]

@external
def literal(m: Msg) -> Msg:
    c: Msg = m
    c.payload = b"new payload"
    c.name = "new name"
    return c

@external
def local(m: Msg, data: Bytes[INF], name: String[INF]) -> (Bytes[INF], String[INF], uint256):
    c: Msg = m
    d: Bytes[INF] = data
    s: String[INF] = name
    c.payload = d
    c.name = s
    return c.payload, c.name, len(c.payload)

@external
def combined(m: Msg) -> Msg:
    c: Msg = m
    c.payload = concat(c.payload, b"-tail")
    c.name = slice(c.name, 0, 3)
    return c

@external
def emptied(m: Msg) -> (Bytes[INF], String[INF], uint256):
    c: Msg = m
    c.payload = b""
    c.name = ""
    return c.payload, c.name, len(c.payload)
    """

    c = get_contract(code)
    m = (b"payload", "longname")
    assert c.literal(m) == (b"new payload", "new name")
    assert c.local(m, b"x" * 70, "y" * 40) == (b"x" * 70, "y" * 40, 70)
    assert c.combined(m) == (b"payload-tail", "lon")
    assert c.emptied(m) == (b"", "", 0)


def test_member_assign_from_tuple_unpack(get_contract):
    code = BATCH + """
@internal
def g() -> (uint256, DynArray[uint256, INF]):
    return 7, [8, 9]

@external
def f(b: Batch) -> (uint256, DynArray[uint256, INF], uint256):
    c: Batch = b
    x: uint256 = 0
    x, c.values = self.g()
    c.values.append(10)
    return x, c.values, len(c.values)
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == (7, [8, 9, 10], 3)


def test_member_assign_from_bounded_tuple_unpack(get_contract):
    # a source tuple without unbounded members is unpacked member by member
    code = BATCH + """
@internal
def g() -> (uint256, DynArray[uint256, 3]):
    return 7, [8, 9]

@external
def f(b: Batch) -> (uint256, DynArray[uint256, INF], uint256, uint256):
    c: Batch = b
    d: Batch = c
    x: uint256 = 0
    x, c.values = self.g()
    c.values.append(10)
    return x, c.values, len(c.values), len(d.values)
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == (7, [8, 9, 10], 3, 3)


def test_mutated_struct_abi_roundtrip(get_contract, env):
    code = BATCH + """
@external
def f(b: Batch) -> Batch:
    c: Batch = b
    c.values.append(4)
    c.values[0] = 10
    return c
    """

    c = get_contract(code)
    calldata = method_id("f((address,uint256[]))") + eth_abi_encode(
        ["(address,uint256[])"], [(OWNER, [1, 2, 3])]
    )
    output = env.message_call(c.address, data=calldata)
    decoded_owner, decoded_values = eth_abi_decode(["(address,uint256[])"], output)[0]
    assert decoded_owner == OWNER
    assert list(decoded_values) == [10, 2, 3, 4]


def test_member_read_does_not_copy_payload(compiler_settings):
    # only a write through the member copies its payload. The one dynamic
    # allocation here is the calldata decode of the member payload; a read
    # that copied the payload would add a second one
    code = BATCH + """
@external
def f(b: Batch, i: uint256) -> (uint256, uint256):
    c: Batch = b
    acc: uint256 = 0
    for v: uint256 in c.values:
        acc += v
    return acc, c.values[i]
    """

    compiler_data = CompilerData(code, settings=compiler_settings)
    with anchor_settings(compiler_settings):
        ctx = generate_venom_runtime(compiler_data.global_ctx, compiler_settings)
    dallocas = [
        inst
        for fn in ctx.functions.values()
        for bb in fn.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "dalloca"
    ]
    assert len(dallocas) == 1


# Copies of a struct never observe each other's member mutation. After a
# struct copy both structs share the member's payload, so the first write
# through either side copies it. Every source below is appended to twice
# before it is copied, so that its array has room to grow in place and an
# in-place write into the shared payload would be possible. (A struct
# returned from an internal call has no such room, so the appends are
# inline.)

PREPARE = """
    src: Batch = b
    src.values.append(4)
    src.values.append(5)
"""


def test_copy_then_mutate_copy(get_contract):
    code = (
        BATCH
        + """
@external
def declared(b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
"""
        + PREPARE
        + """
    copy: Batch = src
    copy.values.append(8)
    copy.values[0] = 100
    return src.values, copy.values

@external
def reassigned(b: Batch, other: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
"""
        + PREPARE
        + """
    copy: Batch = other
    copy = src
    copy.values.append(8)
    copy.values[0] = 100
    return src.values, copy.values
    """
    )

    c = get_contract(code)
    b = (OWNER, [1, 2, 3])
    assert c.declared(b) == ([1, 2, 3, 4, 5], [100, 2, 3, 4, 5, 8])
    assert c.reassigned(b, (OWNER, [9])) == ([1, 2, 3, 4, 5], [100, 2, 3, 4, 5, 8])


def test_copy_then_mutate_source(get_contract):
    # fails if a struct copy leaves the source's room to grow in place: the
    # source then appends into the payload the copy still references
    code = (
        BATCH
        + """
@external
def f(b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
"""
        + PREPARE
        + """
    copy: Batch = src
    src.values.append(8)
    src.values[0] = 100
    return src.values, copy.values
    """
    )

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == ([100, 2, 3, 4, 5, 8], [1, 2, 3, 4, 5])


def test_copy_then_store_member_element(get_contract):
    # fails if an element store goes into a payload the struct shares
    code = (
        BATCH
        + """
@external
def into_copy(b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
"""
        + PREPARE
        + """
    copy: Batch = src
    copy.values[0] = 100
    copy.values[1] += 100
    return src.values, copy.values

@external
def into_source(b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
"""
        + PREPARE
        + """
    copy: Batch = src
    src.values[0] = 100
    src.values[1] += 100
    return src.values, copy.values
    """
    )

    c = get_contract(code)
    assert c.into_copy((OWNER, [1, 2, 3])) == ([1, 2, 3, 4, 5], [100, 102, 3, 4, 5])
    assert c.into_source((OWNER, [1, 2, 3])) == ([100, 102, 3, 4, 5], [1, 2, 3, 4, 5])


def test_copy_then_assign_empty_member(get_contract):
    # fails if the empty-value fast path zeroes the length word of the
    # payload the copy shares with its source
    code = BATCH + """
@external
def f(b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
    src: Batch = b
    copy: Batch = src
    copy.values = []
    return src.values, copy.values
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == ([1, 2, 3], [])


def test_copy_then_pop_member(get_contract):
    # fails if pop decrements the length of the shared payload in place
    code = BATCH + """
@external
def f(b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF], uint256):
    src: Batch = b
    copy: Batch = src
    x: uint256 = copy.values.pop()
    return src.values, copy.values, x
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == ([1, 2, 3], [1, 2], 3)


def test_member_store_with_pop_in_index(get_contract):
    # the store target `copy.values` is lowered before the index, and the
    # index pops the same member; fails if the first write leaves the member
    # in a state where the pop copies the payload again, so that the store
    # lands in a payload the member no longer refers to
    code = BATCH + """
@external
def f(b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
    src: Batch = b
    copy: Batch = src
    copy.values[copy.values.pop() - 3] = 100
    return src.values, copy.values
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == ([1, 2, 3], [100, 2])


def test_member_copy_to_local_is_independent(get_contract):
    code = (
        BATCH
        + """
@external
def f(b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
"""
        + PREPARE
        + """
    v: DynArray[uint256, INF] = src.values
    v.append(6)
    src.values.append(7)
    v[0] = 100
    src.values[1] = 200
    return src.values, v
    """
    )

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == ([1, 200, 3, 4, 5, 7], [100, 2, 3, 4, 5, 6])


@pytest.mark.parametrize("inlining", [True, False])
def test_internal_call_arg_mutation_stays_in_callee(
    get_contract, compiler_settings, no_inlining_settings, inlining
):
    code = (
        BATCH
        + """
@internal
def mutate(b: Batch) -> Batch:
    b.values.append(9)
    b.values[0] = 100
    return b

@external
def f(b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
"""
        + PREPARE
        + """
    out: Batch = self.mutate(src)
    src.values.append(6)
    return src.values, out.values
    """
    )

    settings = compiler_settings if inlining else no_inlining_settings
    c = get_contract(code, compiler_settings=settings)
    assert c.f((OWNER, [1, 2, 3])) == ([1, 2, 3, 4, 5, 6], [100, 2, 3, 4, 5, 9])


@pytest.mark.parametrize("bound", ["3", "INF"])
def test_array_element_copy_then_mutate(get_contract, bound):
    code = BATCH + f"""
@external
def f(bs: DynArray[Batch, {bound}]) -> (
    DynArray[uint256, INF], DynArray[uint256, INF], DynArray[uint256, INF], uint256
):
    xs: DynArray[Batch, {bound}] = bs
    b: Batch = xs[1]
    b.values.append(9)
    b.values.append(10)
    xs[1] = b
    b.values.append(11)
    b.values[0] = 100
    ys: DynArray[Batch, {bound}] = xs
    ys[0] = b
    b.values.append(12)
    acc: uint256 = 0
    for e: Batch in xs:
        acc += len(e.values)
    return xs[1].values, ys[0].values, b.values, acc
    """

    c = get_contract(code)
    bs = [(OWNER, [1]), (OWNER, [2, 3]), (OWNER, [4, 5, 6])]
    assert c.f(bs) == ([2, 3, 9, 10], [100, 3, 9, 10, 11], [100, 3, 9, 10, 11, 12], 8)


def test_internal_return_then_mutate(get_contract):
    code = BATCH + """
@internal
def g(x: uint256) -> Batch:
    return Batch(owner=self, values=[x, x + 1])

@external
def f() -> (DynArray[uint256, INF], DynArray[uint256, INF]):
    first: Batch = self.g(1)
    first.values.append(3)
    first.values[0] = 10
    second: Batch = self.g(99)
    second.values.pop()
    return first.values, second.values
    """

    c = get_contract(code)
    assert c.f() == ([10, 2, 3], [99])


def test_struct_constructor_member_copy_then_mutate(get_contract):
    code = (
        BATCH
        + """
struct Outer:
    tag: uint256
    inner: Batch

@external
def f(b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
"""
        + PREPARE
        + """
    o: Outer = Outer(tag=1, inner=src)
    src.values.append(6)
    o.inner.values.append(7)
    return src.values, o.inner.values
    """
    )

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == ([1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 7])


def test_list_literal_copy_then_mutate(get_contract):
    code = (
        BATCH
        + """
@external
def f(b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF], DynArray[uint256, INF]):
"""
        + PREPARE
        + """
    xs: DynArray[Batch, 2] = [src, src]
    src.values.append(6)
    src.values[0] = 100
    return src.values, xs[0].values, xs[1].values
    """
    )

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == ([100, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5])


# empty(). Every cell of the zeroed struct points at its own empty payload,
# the same 32-byte zero length word an empty unbounded local uses.

ZERO_ADDRESS = "0x" + "00" * 20


def test_empty_struct(get_contract):
    code = BATCH + """
@external
def size() -> uint256:
    b: Batch = empty(Batch)
    return len(b.values)

@external
def f() -> Batch:
    b: Batch = empty(Batch)
    b.values.append(7)
    b.values.append(8)
    return b
    """

    c = get_contract(code)
    assert c.size() == 0
    assert c.f() == (ZERO_ADDRESS, [7, 8])


def test_empty_struct_returned_directly(get_contract):
    code = BATCH + """
@external
def f() -> Batch:
    return empty(Batch)
    """

    c = get_contract(code)
    assert c.f() == (ZERO_ADDRESS, [])


def test_empty_struct_copy_is_independent(get_contract):
    code = BATCH + """
@external
def f() -> (DynArray[uint256, INF], DynArray[uint256, INF]):
    a: Batch = empty(Batch)
    b: Batch = a
    b.values.append(1)
    a.values.append(2)
    a.values.append(3)
    return a.values, b.values
    """

    c = get_contract(code)
    assert c.f() == ([2, 3], [1])


def test_empty_struct_bytes_and_string_members(get_contract):
    code = """
struct Msg:
    kind: uint256
    payload: Bytes[INF]
    name: String[INF]

@external
def sizes() -> (uint256, uint256):
    m: Msg = empty(Msg)
    return len(m.payload), len(m.name)

@external
def f() -> Msg:
    m: Msg = empty(Msg)
    m.payload = b"hello"
    return m
    """

    c = get_contract(code)
    assert c.sizes() == (0, 0)
    assert c.f() == (0, b"hello", "")


def test_empty_nested_struct(get_contract):
    code = BATCH + """
struct Msg:
    kind: uint256
    payload: Bytes[INF]

struct Outer:
    tag: uint256
    inner: Batch
    msg: Msg

@external
def sizes() -> (uint256, uint256):
    o: Outer = empty(Outer)
    return len(o.inner.values), len(o.msg.payload)

@external
def f() -> Outer:
    o: Outer = empty(Outer)
    o.inner.values.append(5)
    o.msg.payload = b"x"
    return o
    """

    c = get_contract(code)
    assert c.sizes() == (0, 0)
    assert c.f() == (0, (ZERO_ADDRESS, [5]), (0, b"x"))


def test_empty_struct_as_internal_call_arg(get_contract):
    code = BATCH + """
@internal
def total(b: Batch) -> uint256:
    acc: uint256 = 0
    for v: uint256 in b.values:
        acc += v
    return acc

@external
def f() -> uint256:
    return self.total(empty(Batch))
    """

    c = get_contract(code)
    assert c.f() == 0


def test_empty_struct_as_default_return_value(env, get_contract):
    caller_code = BATCH + """
interface Maker:
    def make() -> Batch: view

@external
def f(target: address) -> Batch:
    b: Batch = staticcall Maker(target).make(default_return_value=empty(Batch))
    b.values.append(1)
    return b
    """

    caller = get_contract(caller_code)
    empty_target = deploy_raw_returner(env, b"")
    assert caller.f(empty_target.address) == (ZERO_ADDRESS, [1])


# External calls. The encoded size of such a struct has no static bound: the
# argument buffer is sized at runtime, and the returndata is copied to
# scratch and decoded like a calldata argument.

SUMMER = BATCH + """
@external
def take(b: Batch) -> (uint256, uint256):
    acc: uint256 = 0
    for v: uint256 in b.values:
        acc += v
    return acc, len(b.values)
"""

MAKER = BATCH + """
@external
@view
def make(owner: address, n: uint256) -> Batch:
    b: Batch = Batch(owner=owner, values=[])
    for i: uint256 in range(n, bound=100):
        b.values.append(i + 1)
    return b
"""


@pytest.mark.parametrize("n", LENGTHS)
def test_extcall_struct_arg(get_contract, n):
    caller_code = BATCH + """
interface Summer:
    def take(b: Batch) -> (uint256, uint256): nonpayable

@external
def f(target: address, b: Batch) -> (uint256, uint256, uint256):
    c: Batch = b
    total: uint256 = 0
    count: uint256 = 0
    total, count = extcall Summer(target).take(c)
    c.values.append(100)
    return total, count, len(c.values)
    """

    summer = get_contract(SUMMER)
    caller = get_contract(caller_code)
    values = list(range(1, n + 1))
    assert caller.f(summer.address, (OWNER, values)) == (sum(values), n, n + 1)


def test_extcall_struct_arg_with_other_args(get_contract):
    callee_code = BATCH + """
@external
def take(x: uint256, b: Batch, s: String[8]) -> (uint256, address, String[8]):
    return x + len(b.values), b.owner, s
    """
    caller_code = BATCH + """
interface Callee:
    def take(x: uint256, b: Batch, s: String[8]) -> (uint256, address, String[8]): nonpayable

@external
def f(target: address, b: Batch) -> (uint256, address, String[8]):
    return extcall Callee(target).take(10, b, "tail")
    """

    callee = get_contract(callee_code)
    caller = get_contract(caller_code)
    assert caller.f(callee.address, (OWNER, [1, 2, 3])) == (13, OWNER, "tail")


@pytest.mark.parametrize("n", [0, 1, 32, 100])
def test_extcall_bytes_member_arg(get_contract, n):
    msg = """
struct Msg:
    kind: uint256
    payload: Bytes[INF]
"""
    callee_code = msg + """
@external
def take(m: Msg) -> (uint256, uint256, bytes32):
    return m.kind, len(m.payload), keccak256(m.payload)
    """
    caller_code = msg + """
interface Callee:
    def take(m: Msg) -> (uint256, uint256, bytes32): nonpayable

@external
def f(target: address, m: Msg) -> (uint256, uint256, bytes32):
    return extcall Callee(target).take(m)
    """

    callee = get_contract(callee_code)
    caller = get_contract(caller_code)
    payload = bytes(range(256))[:n]
    assert caller.f(callee.address, (7, payload)) == (7, n, keccak256(payload))


def test_extcall_nested_struct_arg(get_contract):
    outer = BATCH + """
struct Outer:
    tag: uint256
    inner: Batch
"""
    callee_code = outer + """
@external
def take(o: Outer) -> (uint256, uint256, uint256):
    return o.tag, len(o.inner.values), o.inner.values[1]
    """
    caller_code = outer + """
interface Callee:
    def take(o: Outer) -> (uint256, uint256, uint256): nonpayable

@external
def f(target: address, b: Batch) -> (uint256, uint256, uint256):
    o: Outer = Outer(tag=5, inner=b)
    return extcall Callee(target).take(o)
    """

    callee = get_contract(callee_code)
    caller = get_contract(caller_code)
    assert caller.f(callee.address, (OWNER, [1, 2, 3])) == (5, 3, 2)


@pytest.mark.parametrize("n", LENGTHS)
def test_staticcall_struct_return(get_contract, n):
    caller_code = BATCH + """
interface Maker:
    def make(owner: address, n: uint256) -> Batch: view

@external
def f(target: address, owner: address, n: uint256) -> (address, uint256, uint256):
    b: Batch = staticcall Maker(target).make(owner, n)
    last: uint256 = 0
    if len(b.values) > 0:
        last = b.values[len(b.values) - 1]
    return b.owner, len(b.values), last
    """

    maker = get_contract(MAKER)
    caller = get_contract(caller_code)
    assert caller.f(maker.address, OWNER, n) == (OWNER, n, n)


def test_staticcall_struct_return_echo(get_contract):
    caller_code = BATCH + """
interface Maker:
    def make(owner: address, n: uint256) -> Batch: view

@external
def f(target: address, owner: address, n: uint256) -> Batch:
    return staticcall Maker(target).make(owner, n)
    """

    maker = get_contract(MAKER)
    caller = get_contract(caller_code)
    assert caller.f(maker.address, OWNER, 3) == (OWNER, [1, 2, 3])


def test_staticcall_struct_return_survives_second_call(get_contract):
    caller_code = BATCH + """
interface Maker:
    def make(owner: address, n: uint256) -> Batch: view

@external
def f(target: address) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
    first: Batch = staticcall Maker(target).make(self, 2)
    first.values.append(50)
    second: Batch = staticcall Maker(target).make(self, 3)
    second.values[0] = 60
    return first.values, second.values
    """

    maker = get_contract(MAKER)
    caller = get_contract(caller_code)
    assert caller.f(maker.address) == ([1, 2, 50], [60, 2, 3])


def test_staticcall_struct_return_with_default(env, get_contract):
    caller_code = BATCH + """
interface Maker:
    def make() -> Batch: view

@external
def f(target: address) -> Batch:
    return staticcall Maker(target).make(default_return_value=Batch(owner=self, values=[7, 8]))
    """

    caller = get_contract(caller_code)
    empty_target = deploy_raw_returner(env, b"")
    assert caller.f(empty_target.address) == (caller.address, [7, 8])

    target = deploy_raw_returner(env, eth_abi_encode(["(address,uint256[])"], [(OWNER, [1, 2, 3])]))
    assert caller.f(target.address) == (OWNER, [1, 2, 3])


def test_staticcall_struct_return_default_is_independent(env, get_contract):
    # the default keeps room for in-place appends; neither the result nor
    # the default may observe a write through the other
    caller_code = BATCH + """
interface Maker:
    def make() -> Batch: view

@external
def f(target: address, b: Batch) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
    fallback: Batch = b
    fallback.values.append(4)
    fallback.values.append(5)
    r: Batch = staticcall Maker(target).make(default_return_value=fallback)
    r.values.append(9)
    r.values[0] = 100
    fallback.values.append(6)
    fallback.values[1] = 200
    return r.values, fallback.values
    """

    caller = get_contract(caller_code)
    empty_target = deploy_raw_returner(env, b"")
    assert caller.f(empty_target.address, (OWNER, [1, 2, 3])) == (
        [100, 2, 3, 4, 5, 9],
        [1, 200, 3, 4, 5, 6],
    )


# abi_encode / abi_decode. The encoding buffer is sized at runtime; the
# decoder bounds every member by the end of the input instead of by a size
# bound of the type.


@pytest.mark.parametrize("n", LENGTHS)
def test_abi_encode_struct(get_contract, n):
    code = BATCH + """
@external
def enc(b: Batch) -> Bytes[INF]:
    return abi_encode(b)

@external
def enc_no_tuple(b: Batch) -> Bytes[INF]:
    return abi_encode(b, ensure_tuple=False)

@external
def enc_method_id(b: Batch, x: uint256) -> Bytes[INF]:
    return abi_encode(b, x, method_id=method_id("take((address,uint256[]),uint256)"))
    """

    c = get_contract(code)
    values = list(range(1, n + 1))
    b = (OWNER, values)
    assert c.enc(b) == eth_abi_encode(["(address,uint256[])"], [b])
    assert c.enc_no_tuple(b) == eth_abi_encode(["address", "uint256[]"], list(b))
    assert c.enc_method_id(b, 7) == method_id("take((address,uint256[]),uint256)") + eth_abi_encode(
        ["(address,uint256[])", "uint256"], [b, 7]
    )


def test_abi_encode_struct_bytes_and_nested_members(get_contract):
    code = BATCH + """
struct Msg:
    kind: uint256
    payload: Bytes[INF]

struct Outer:
    tag: uint256
    inner: Batch
    msg: Msg

@external
def enc(o: Outer) -> Bytes[INF]:
    return abi_encode(o)
    """

    c = get_contract(code)
    o = (5, (OWNER, [1, 2, 3]), (9, b"hello unbounded world"))
    assert c.enc(o) == eth_abi_encode(["(uint256,(address,uint256[]),(uint256,bytes))"], [o])


@pytest.mark.parametrize("n", LENGTHS)
def test_abi_decode_struct(get_contract, n):
    code = BATCH + """
@external
def dec(d: Bytes[INF]) -> Batch:
    return abi_decode(d, Batch)

@external
def dec_no_tuple(d: Bytes[INF]) -> Batch:
    return abi_decode(d, Batch, unwrap_tuple=False)

@external
def roundtrip(b: Batch) -> (address, uint256, uint256):
    d: Bytes[INF] = abi_encode(b)
    c: Batch = abi_decode(d, Batch)
    c.values.append(100)
    return c.owner, len(c.values), c.values[len(c.values) - 1]
    """

    c = get_contract(code)
    values = list(range(1, n + 1))
    b = (OWNER, values)
    assert c.dec(eth_abi_encode(["(address,uint256[])"], [b])) == b
    assert c.dec_no_tuple(eth_abi_encode(["address", "uint256[]"], list(b))) == b
    assert c.roundtrip(b) == (OWNER, n + 1, 100)


def test_abi_decode_struct_bytes_and_nested_members(get_contract):
    code = BATCH + """
struct Msg:
    kind: uint256
    payload: Bytes[INF]

struct Outer:
    tag: uint256
    inner: Batch
    msg: Msg

@external
def dec(d: Bytes[INF]) -> Outer:
    return abi_decode(d, Outer)
    """

    c = get_contract(code)
    o = (5, (OWNER, [1, 2, 3]), (9, b"hello unbounded world"))
    assert c.dec(eth_abi_encode(["(uint256,(address,uint256[]),(uint256,bytes))"], [o])) == o


# Malformed and non-canonical input. Every ingress path (calldata argument,
# external call return, abi_decode in both unwrap modes) runs the calldata
# decoder over a copy of the bytes, so each case must have the same outcome
# on every path: the decoded value, or a revert.

_INGRESS_CODE = """
struct Msg:
    owner: address
    values: DynArray[uint256, INF]
    payload: Bytes[INF]

interface Source:
    def data() -> Msg: view

@external
def from_calldata(m: Msg) -> Msg:
    return m

@external
def from_returndata(addr: address) -> Msg:
    return staticcall Source(addr).data()

@external
def from_bytes(d: Bytes[INF]) -> Msg:
    return abi_decode(d, Msg)

@external
def from_bytes_no_tuple(d: Bytes[INF]) -> Msg:
    return abi_decode(d, Msg, unwrap_tuple=False)
"""

_INGRESS_PATHS = ("calldata", "returndata", "abi_decode", "abi_decode_no_tuple")

# the struct head is three words: owner, values offset, payload offset
_HEAD_SIZE = 96
_VALUES_TAIL = word(1) + word(9)
_PAYLOAD_TAIL = word(5) + b"hello".ljust(32, b"\0")


def _msg_body(values_offset, payload_offset, tail=b""):
    """Encoding of a Msg starting at its head; offsets are relative to the head."""
    return word(int(OWNER, 16)) + word(values_offset) + word(payload_offset) + tail


_CANONICAL = (OWNER, [9], b"hello")

# (name, body, expected): `body` starts at the struct head, `expected` is
# None when decoding must be rejected
_MALFORMED_CASES = [
    ("canonical", _msg_body(96, 160, _VALUES_TAIL + _PAYLOAD_TAIL), _CANONICAL),
    ("empty", b"", None),
    ("head_truncated_after_owner", word(int(OWNER, 16)), None),
    ("head_truncated_before_payload_offset", word(int(OWNER, 16)) + word(96), None),
    ("values_offset_without_length_word", _msg_body(96, 96), None),
    ("values_count_past_end", _msg_body(96, 160, word(2**32) + _PAYLOAD_TAIL), None),
    ("values_one_element_short", _msg_body(160, 96, _PAYLOAD_TAIL + word(2) + word(9)), None),
    ("values_offset_outside_body", _msg_body(224, 96, _PAYLOAD_TAIL), None),
    ("values_offset_wraps", _msg_body(2**256 - 32, 96, _PAYLOAD_TAIL), None),
    # the count word is the payload offset word
    ("values_offset_points_into_head", _msg_body(32, 96, _PAYLOAD_TAIL), None),
    ("payload_offset_outside_body", _msg_body(96, 224, _VALUES_TAIL), None),
    ("payload_length_past_end", _msg_body(96, 160, _VALUES_TAIL + word(64)), None),
    # the length word is the owner word
    ("payload_offset_points_at_head", _msg_body(96, 0, _VALUES_TAIL), None),
    # accepted non-canonical encodings
    (
        "payload_length_5_unpadded",
        _msg_body(96, 160, _VALUES_TAIL + word(5) + b"hello"),
        _CANONICAL,
    ),
    (
        "values_length_zero_with_trailing_word",
        _msg_body(96, 160, word(0) + word(7) + _PAYLOAD_TAIL),
        (OWNER, [], b"hello"),
    ),
    ("trailing_garbage", _msg_body(96, 160, _VALUES_TAIL + _PAYLOAD_TAIL + b"garbage"), _CANONICAL),
    (
        "values_offset_skips_a_word",
        _msg_body(128, 192, word(0xDEAD) + _VALUES_TAIL + _PAYLOAD_TAIL),
        _CANONICAL,
    ),
    (
        "member_offsets_unaligned",
        _msg_body(97, 161, b"\0" + _VALUES_TAIL + _PAYLOAD_TAIL),
        _CANONICAL,
    ),
    (
        "values_tail_overlaps_payload_tail",
        _msg_body(96, 160, word(2) + word(9) + _PAYLOAD_TAIL),
        (OWNER, [9, 5], b"hello"),
    ),
    # the payload's length word is the element count, its data the first element
    (
        "both_members_alias_the_same_tail",
        _msg_body(96, 96, word(2) + word(9) + word(8)),
        (OWNER, [9, 8], b"\0\0"),
    ),
]

# (name, payload, expected): cases about the offset word that wraps the
# struct, which only the tuple-wrapped paths read
_MALFORMED_WRAPPED_CASES = [
    ("wrapped_empty", b"", None),
    ("struct_offset_word_only", word(32), None),
    ("struct_offset_outside_payload", word(1000) + _MALFORMED_CASES[0][1], None),
    ("struct_offset_wraps", word(2**256 - 31) + _MALFORMED_CASES[0][1], None),
    ("struct_offset_skips_a_word", word(64) + word(0xDEAD) + _MALFORMED_CASES[0][1], _CANONICAL),
]


@pytest.fixture(scope="module")
def ingress(get_contract, experimental_codegen):
    # module-scoped, so it is set up before the function-scoped skip above
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")
    return get_contract(_INGRESS_CODE)


def _run_ingress(env, c, path, payload):
    if path == "calldata":
        selector = method_id("from_calldata((address,uint256[],bytes))")
        ret = env.message_call(c.address, data=selector + payload)
        return abi_decode("((address,uint256[],bytes))", ret)[0]
    if path == "returndata":
        return c.from_returndata(deploy_raw_returner(env, payload).address)
    if path == "abi_decode":
        return c.from_bytes(payload)
    assert path == "abi_decode_no_tuple"
    return c.from_bytes_no_tuple(payload)


def _check_ingress(env, ingress, tx_failed, path, payload, expected):
    if expected is None:
        with tx_failed():
            _run_ingress(env, ingress, path, payload)
    else:
        assert _run_ingress(env, ingress, path, payload) == expected, path


@pytest.mark.parametrize(
    ("body", "expected"),
    [pytest.param(body, expected, id=name) for name, body, expected in _MALFORMED_CASES],
)
def test_malformed_struct_same_outcome_on_every_ingress_path(
    env, ingress, tx_failed, body, expected
):
    for path in _INGRESS_PATHS:
        payload = body if path == "abi_decode_no_tuple" else word(32) + body
        _check_ingress(env, ingress, tx_failed, path, payload, expected)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(payload, expected, id=name)
        for name, payload, expected in _MALFORMED_WRAPPED_CASES
    ],
)
def test_malformed_struct_offset_same_outcome_on_every_wrapped_path(
    env, ingress, tx_failed, payload, expected
):
    for path in _INGRESS_PATHS[:-1]:
        _check_ingress(env, ingress, tx_failed, path, payload, expected)


# Events, custom errors, print and create_*: the same runtime-sized encoding
# as external call arguments.


@pytest.mark.parametrize("n", LENGTHS)
def test_event_with_struct_member(env, get_contract, n):
    code = BATCH + """
event Submitted:
    sender: indexed(address)
    batch: Batch
    nonce: uint256

@external
def submit(b: Batch, nonce: uint256):
    log Submitted(sender=msg.sender, batch=b, nonce=nonce)
    """

    c = get_contract(code)
    values = list(range(1, n + 1))
    c.submit((OWNER, values), 7)
    topics, data = env.get_logs(c, raw=True)[0]
    assert len(topics) == 2
    assert data == eth_abi_encode(["(address,uint256[])", "uint256"], [(OWNER, values), 7])


def test_event_with_nested_struct_member(env, get_contract):
    code = BATCH + """
struct Outer:
    tag: uint256
    inner: Batch

event E:
    o: Outer

@external
def emit_it(b: Batch):
    log E(o=Outer(tag=3, inner=b))
    """

    c = get_contract(code)
    c.emit_it((OWNER, [4, 5]))
    assert env.get_logs(c, raw=True)[0][1] == eth_abi_encode(
        ["(uint256,(address,uint256[]))"], [(3, (OWNER, [4, 5]))]
    )


@pytest.mark.parametrize("n", LENGTHS)
def test_custom_error_with_struct_member(get_contract, n):
    code = BATCH + """
error Rejected:
    batch: Batch
    reason: uint256

@external
def boom(b: Batch):
    raise Rejected(batch=b, reason=42)
    """

    c = get_contract(code)
    values = list(range(1, n + 1))
    with pytest.raises(ExecutionReverted) as excinfo:
        c.boom((OWNER, values))
    revert_hex = excinfo.value.args[0]
    assert bytes.fromhex(revert_hex.removeprefix("0x")) == method_id(
        "Rejected((address,uint256[]),uint256)"
    ) + eth_abi_encode(["(address,uint256[])", "uint256"], [(OWNER, values), 42])


def test_print_struct(get_contract, compiler_settings):
    # the console call cannot be observed by the test harness; the runtime
    # code is checked for the wire format instead: the `log(string,bytes)`
    # selector with the struct's ABI schema, and the hardhat selector
    code = BATCH + """
@external
def f(b: Batch) -> uint256:
    print(b)
    print(b, hardhat_compat=True)
    return len(b.values)
    """

    c = get_contract(code)
    assert c.f((OWNER, [1, 2, 3])) == 3

    out = compile_code(code, output_formats=["bytecode_runtime"], settings=compiler_settings)
    runtime = out["bytecode_runtime"]
    assert method_id("log(string,bytes)").hex() in runtime
    assert b"((address,uint256[]))".hex() in runtime
    assert method_id("log((address,uint256[]))").hex() in runtime


def test_create_from_blueprint_with_struct_arg(env, get_contract, deploy_blueprint_for):
    child_code = BATCH + """
count: public(uint256)
last: public(uint256)
owner: public(address)

@deploy
def __init__(b: Batch, tag: uint256):
    self.count = len(b.values)
    self.last = b.values[len(b.values) - 1] + tag
    self.owner = b.owner
    """
    blueprint, _ = deploy_blueprint_for(child_code)

    deployer_code = BATCH + """
@external
def deploy(target: address, b: Batch, tag: uint256) -> address:
    return create_from_blueprint(target, b, tag)
    """

    deployer = get_contract(deployer_code)
    addr = deployer.deploy(blueprint.address, (OWNER, [5, 6, 7]), 100)
    assert eth_abi_decode(["uint256"], env.message_call(addr, data=method_id("count()"))) == (3,)
    assert eth_abi_decode(["uint256"], env.message_call(addr, data=method_id("last()"))) == (107,)
    assert eth_abi_decode(["address"], env.message_call(addr, data=method_id("owner()"))) == (
        OWNER.lower(),
    )
