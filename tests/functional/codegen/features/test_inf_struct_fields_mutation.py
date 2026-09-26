import pytest
from eth_abi import decode as eth_abi_decode
from eth_abi import encode as eth_abi_encode

from vyper.codegen_venom.module import generate_venom_runtime
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import anchor_settings
from vyper.utils import method_id


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


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


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize(
    "source, otherwise",
    [
        ("b.rows[0]", [1, 2]),
        ("b.rows[0] if flag else [8]", [8]),
        ("b.rows[0] if flag else c.rows[0]", [0]),
        ("(b.rows[0], c.rows[0])[0]", [1, 2]),
        ("(b if flag else c).rows[0]", [0]),
        ("b.rows[0] if flag else (c.rows[0] if other else [8])", [0]),
    ],
)
def test_member_source_frozen_before_target(get_contract, source, otherwise, owned):
    prepare = "b.rows.append([5])\n    b.rows.pop()" if owned else "pass"
    code = f"""
struct S:
    rows: DynArray[DynArray[uint256, 4], INF]

@external
def f(flag: bool, other: bool) -> (DynArray[uint256, 4], DynArray[uint256, 4]):
    b: S = S(rows=[[1, 2]])
    c: S = S(rows=[[0]])
    {prepare}
    c.rows[b.rows[0].pop() - 2] = {source}
    return c.rows[0], b.rows[0]
"""
    c = get_contract(code)
    assert c.f(True, True) == ([1, 2], [1])
    assert c.f(False, True) == (otherwise, [1])
    if "other" in source:
        assert c.f(False, False) == ([8], [1])


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("bound", ["4", "INF"])
@pytest.mark.parametrize(
    "base",
    [
        "b.rows",
        "(b.rows if flag else c.rows)",
        "(b.rows if flag else local)",
        "(b.rows if flag else (c.rows if other else local))",
    ],
)
def test_selected_array_checks_length_after_index(get_contract, tx_failed, base, bound, owned):
    prepare = "b.rows.append([7])\n    b.rows.pop()" if owned else "pass"
    code = f"""
struct S:
    rows: DynArray[DynArray[uint256, 4], {bound}]

@external
def f(flag: bool, other: bool) -> uint256:
    b: S = S(rows=[[0], [1]])
    c: S = S(rows=[[3], [4, 5]])
    local: DynArray[DynArray[uint256, 4], {bound}] = [[6], [7, 8, 9]]
    {prepare}
    return len({base}[b.rows.pop()[0]])
"""
    c = get_contract(code)
    with tx_failed():
        c.f(True, True)
    if "flag" in base:
        assert c.f(False, True) == (2 if "c.rows" in base else 3)
    if "other" in base:
        assert c.f(False, False) == 3


@pytest.mark.parametrize("owned", [False, True])
def test_selected_nested_array_snapshot_before_index(get_contract, tx_failed, owned):
    prepare = "b.rows.append([7])\n    b.rows.pop()" if owned else "pass"
    code = f"""
struct S:
    rows: DynArray[DynArray[uint256, 4], INF]

@external
def f(flag: bool) -> uint256:
    b: S = S(rows=[[0], [1]])
    {prepare}
    return (b.rows[0] if flag else [0, 1])[b.rows.pop()[0]]
"""
    c = get_contract(code)
    with tx_failed():
        c.f(True)
    assert c.f(False) == 1


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


# An append or pop on a bounded array reached through an unbounded member
# writes into that member's payload, so a payload the struct shares is copied
# first, as for an element store.

TABLE = """
struct Inner:
    k: uint256
    xs: DynArray[uint256, 4]

struct Table:
    rows: DynArray[DynArray[uint256, 4], INF]
    items: DynArray[Inner, INF]

struct Pair:
    first: Table
    second: Table
    v: uint256
"""

TABLE_ARG = ([[1, 2], [3]], [(7, [1, 2])])

# (statement on TARGET, effect on (rows, items), popped value)
NESTED_BOUNDED_OPS = {
    "rows_append": ("TARGET.rows[0].append(9)", lambda r, i: r[0].append(9), 0),
    "rows_pop": ("TARGET.rows[0].pop()", lambda r, i: r[0].pop(), 0),
    "rows_pop_value": ("v = TARGET.rows[0].pop()", lambda r, i: r[0].pop(), 2),
    "items_append": ("TARGET.items[0].xs.append(9)", lambda r, i: i[0][1].append(9), 0),
    "items_pop": ("TARGET.items[0].xs.pop()", lambda r, i: i[0][1].pop(), 0),
}


def _apply_table_op(op, rows, items):
    rows = [list(row) for row in rows]
    items = [(k, list(xs)) for k, xs in items]
    NESTED_BOUNDED_OPS[op][1](rows, items)
    return (rows, items)


@pytest.mark.parametrize("spare", [False, True])
@pytest.mark.parametrize("mutate_copy", [True, False])
@pytest.mark.parametrize("op", list(NESTED_BOUNDED_OPS))
def test_copy_then_mutate_nested_bounded_member(get_contract, op, mutate_copy, spare):
    # fails if the append or pop goes into the member payload the copy shares
    # with its source. With `spare`, the source's members have room to grow
    # in place before the copy.
    stmt, _, popped = NESTED_BOUNDED_OPS[op]
    target = "copy" if mutate_copy else "src"
    prepare = """
    src.rows.append([5])
    src.items.append(Inner(k=8, xs=[3]))"""
    code = TABLE + f"""
@external
def f(t: Table) -> Pair:
    src: Table = t{prepare if spare else ""}
    copy: Table = src
    v: uint256 = 0
    {stmt.replace("TARGET", target)}
    return Pair(first=src, second=copy, v=v)
    """

    rows, items = TABLE_ARG
    if spare:
        rows = rows + [[5]]
        items = items + [(8, [3])]
    untouched = (rows, items)
    mutated = _apply_table_op(op, rows, items)
    assert mutated != untouched

    c = get_contract(code)
    expected = (untouched, mutated) if mutate_copy else (mutated, untouched)
    assert c.f(TABLE_ARG) == (*expected, popped)


@pytest.mark.parametrize("op", ["rows_append", "rows_pop", "items_append"])
def test_nested_struct_copy_then_mutate_nested_bounded_member(get_contract, op):
    stmt = NESTED_BOUNDED_OPS[op][0]
    code = TABLE + f"""
struct Outer:
    tag: uint256
    inner: Table

@external
def f(o: Outer) -> Pair:
    copy: Outer = o
    v: uint256 = 0
    {stmt.replace("TARGET", "copy.inner")}
    return Pair(first=o.inner, second=copy.inner, v=copy.tag)
    """

    c = get_contract(code)
    assert c.f((1, TABLE_ARG)) == (TABLE_ARG, _apply_table_op(op, *TABLE_ARG), 1)


@pytest.mark.parametrize("inlining", [True, False])
@pytest.mark.parametrize("op", ["rows_append", "rows_pop", "items_append"])
def test_internal_call_arg_nested_bounded_mutation_stays_in_callee(
    get_contract, compiler_settings, no_inlining_settings, op, inlining
):
    stmt = NESTED_BOUNDED_OPS[op][0]
    code = TABLE + f"""
@internal
def mutate(s: Table) -> Table:
    v: uint256 = 0
    {stmt.replace("TARGET", "s")}
    return s

@external
def f(t: Table) -> Pair:
    src: Table = t
    out: Table = self.mutate(src)
    return Pair(first=src, second=out, v=0)
    """

    settings = compiler_settings if inlining else no_inlining_settings
    c = get_contract(code, compiler_settings=settings)
    assert c.f(TABLE_ARG) == (TABLE_ARG, _apply_table_op(op, *TABLE_ARG), 0)


# A statement can copy the struct and then write the same member again before
# its own write lands, e.g. by passing the struct to a function and popping
# from the member in an argument or index. That second write moves the
# member's payload to a fresh buffer, and the statement's own write has to
# follow it.

MOVED = """
struct S:
    rows: DynArray[DynArray[uint256, 4], INF]
    flat: DynArray[uint256, INF]

struct W:
    tag: uint256
    inner: S

struct R:
    a: S
    b: S
    w: W
    v: uint256

@internal
def inspect(s: S) -> uint256:
    return 0

@internal
def touch(s: S) -> uint256:
    c: S = s
    c.rows[0].append(7)
    c.flat.append(7)
    return 0
"""

MOVED_START = ([[1, 2], [0, 1]], [4, 1])

# (statement on T, (rows, flat) after it, v)
MOVED_WRITES = {
    "append_arg": (
        "TARGET.rows[0].append(self.inspect(TARGET) + TARGET.rows[0].pop())",
        ([[1, 2], [0, 1]], [4, 1]),
        0,
    ),
    "append_arg_copy_in_callee": (
        "TARGET.rows[0].append(self.touch(TARGET) + TARGET.rows[0].pop())",
        ([[1, 2], [0, 1]], [4, 1]),
        0,
    ),
    "append_arg_reads_first": (
        "TARGET.rows[1].append(TARGET.rows[0][0] + self.inspect(TARGET) + TARGET.rows[0].pop())",
        ([[1], [0, 1, 3]], [4, 1]),
        0,
    ),
    "append_arg_other_member": (
        "TARGET.rows[0].append(self.inspect(TARGET) + TARGET.flat.pop())",
        ([[1, 2, 1], [0, 1]], [4]),
        0,
    ),
    "append_index": (
        "TARGET.rows[self.inspect(TARGET) + TARGET.rows[1].pop()].append(9)",
        ([[1, 2], [0, 9]], [4, 1]),
        0,
    ),
    "pop_index": (
        "v = TARGET.rows[self.inspect(TARGET) + TARGET.rows[1].pop()].pop()",
        ([[1, 2], []], [4, 1]),
        0,
    ),
    "store_index": (
        "TARGET.rows[self.inspect(TARGET) + TARGET.rows[1].pop()][0] = 9",
        ([[1, 2], [9]], [4, 1]),
        0,
    ),
    "store_row_index": (
        "TARGET.rows[self.inspect(TARGET) + TARGET.rows[1].pop()] = [9]",
        ([[1, 2], [9]], [4, 1]),
        0,
    ),
    "store_index_source": (
        "TARGET.rows[self.inspect(TARGET) + TARGET.rows[0].pop() - 1] = TARGET.rows[0]",
        # the value is copied before the target's index pops from it
        ([[1], [1, 2]], [4, 1]),
        0,
    ),
    "store_flat_index": (
        "TARGET.flat[self.inspect(TARGET) + TARGET.rows[1].pop()] = 9",
        ([[1, 2], [0]], [4, 9]),
        0,
    ),
    "read_index_bounds": ("v = TARGET.flat[TARGET.flat.pop()]", None, 0),
    "read_index_copy_bounds": (
        "v = TARGET.flat[self.inspect(TARGET) + TARGET.flat.pop()]",
        None,
        0,
    ),
    "read_nested_index_bounds": ("v = len(TARGET.rows[TARGET.rows.pop()[1]])", None, 0),
    "read_index": (
        "v = len(TARGET.rows[self.inspect(TARGET) + TARGET.rows[1].pop()])",
        ([[1, 2], [0]], [4, 1]),
        1,
    ),
}


@pytest.mark.parametrize("inlining", [True, False])
@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("target", ["b", "w.inner"])
@pytest.mark.parametrize("case", list(MOVED_WRITES))
def test_write_follows_payload_moved_by_own_statement(
    get_contract, tx_failed, compiler_settings, no_inlining_settings, case, target, owned, inlining
):
    # with `owned`, the member owns its payload before the statement starts
    stmt, after, v = MOVED_WRITES[case]
    prepare = f"""
    {target}.rows[0].append(8)
    {target}.rows[0].pop()"""
    code = MOVED + f"""
@external
def f() -> R:
    a: S = S(rows={MOVED_START[0]}, flat={MOVED_START[1]})
    b: S = a
    w: W = W(tag=6, inner=a)
    v: uint256 = 0{prepare if owned else ""}
    {stmt.replace("TARGET", target)}
    return R(a=a, b=b, w=w, v=v)
    """

    settings = compiler_settings if inlining else no_inlining_settings
    c = get_contract(code, compiler_settings=settings)
    if after is None:
        with tx_failed():
            c.f()
        return
    b, w_inner = (after, MOVED_START) if target == "b" else (MOVED_START, after)
    assert c.f() == (MOVED_START, b, (6, w_inner), v)


# The writes that move the payload can also pop the element the statement
# already resolved. The target is checked again after the argument or index
# runs, so a popped target reverts; an assigned value is copied before the
# target is evaluated, so it is the value from before the pop.

SHRUNK = """
struct S:
    rows: DynArray[DynArray[uint256, 4], INF]
    flat: DynArray[uint256, INF]

struct R:
    src: S
    rows: DynArray[DynArray[uint256, 4], INF]
    flat: DynArray[uint256, INF]
    other: DynArray[DynArray[uint256, 4], INF]
    v: uint256

@internal
def inspect(s: S) -> uint256:
    return 0
"""

SHRUNK_START = ([[1, 2], [0, 1], [3]], [4, 1, 0])

# pops [3], copies b, pops [0, 1] (moving the payload), pops flat's 0
SHRINK = "b.rows.pop()[0] + self.inspect(b) + b.rows.pop()[0] + b.flat.pop()"

# (statement, (rows, flat, other, v) after it or None if it reverts)
SHRUNK_WRITES = {
    "append_dead_receiver": (f"b.rows[2].append({SHRINK})", None),
    "append_live_receiver": (f"b.rows[0].append({SHRINK})", ([[1, 2, 3]], [4, 1], [[0]], 0)),
    "copy_dead_source": (f"c.rows[{SHRINK} - 3] = b.rows[2]", ([[1, 2]], [4, 1], [[3]], 0)),
    "copy_changed_then_popped_source": (
        "c.rows[self.inspect(b) + b.rows[1].pop() - 1 + b.rows.pop()[0] * b.rows.pop()[0]]"
        " = b.rows[1]",
        ([[1, 2]], [4, 1, 0], [[0, 1]], 0),
    ),
    "copy_live_source": (f"c.rows[{SHRINK} - 3] = b.rows[0]", ([[1, 2]], [4, 1], [[1, 2]], 0)),
    "pop_index": (f"v = b.rows[{SHRINK} - 3].pop()", ([[1]], [4, 1], [[0]], 2)),
    "store_index": (f"b.rows[{SHRINK} - 3] = [7]", ([[7]], [4, 1], [[0]], 0)),
    "store_index_out_of_range": (f"b.rows[{SHRINK} - 2] = [7]", None),
    "read_index_out_of_range": (f"v = len(b.rows[{SHRINK} - 2])", None),
}


@pytest.mark.parametrize("inlining", [True, False])
@pytest.mark.parametrize("case", list(SHRUNK_WRITES))
def test_write_after_payload_moved_and_shrunk(
    get_contract, tx_failed, compiler_settings, no_inlining_settings, case, inlining
):
    stmt, expected = SHRUNK_WRITES[case]
    code = SHRUNK + f"""
@external
def f() -> R:
    a: S = S(rows={SHRUNK_START[0]}, flat={SHRUNK_START[1]})
    b: S = a
    c: S = S(rows=[[0]], flat=[])
    v: uint256 = 0
    {stmt}
    return R(src=a, rows=b.rows, flat=b.flat, other=c.rows, v=v)
    """

    settings = compiler_settings if inlining else no_inlining_settings
    c = get_contract(code, compiler_settings=settings)
    if expected is None:
        with tx_failed():
            c.f()
        return
    assert c.f() == (SHRUNK_START, *expected)


# An index that pops the array holding the indexed member reads the member
# as it was before the pop, as for a bounded member.

POPPED_HOLDER = """
struct T:
    xs: DynArray[uint256, INF]
    n: uint256

struct S:
    items: DynArray[T, INF]
"""

POPPED_HOLDER_READS = {
    "local_array": """
    ts: DynArray[T, 3] = [T(xs=[4, 5], n=1)]
    return ts[0].xs[ts.pop().n]""",
    "unbounded_local_array": """
    ts: DynArray[T, INF] = [T(xs=[4, 5], n=1)]
    return ts[0].xs[ts.pop().n]""",
    "member_array": """
    b: S = S(items=[T(xs=[4, 5], n=1)])
    return b.items[0].xs[b.items.pop().n]""",
    "member_array_shared": """
    a: S = S(items=[T(xs=[4, 5], n=1)])
    b: S = a
    return b.items[0].xs[b.items.pop().n] + len(a.items) * 10""",
}


@pytest.mark.parametrize("case", list(POPPED_HOLDER_READS))
def test_index_pops_array_holding_member(get_contract, case):
    code = POPPED_HOLDER + f"""
@external
def f() -> uint256:{POPPED_HOLDER_READS[case]}
    """

    expected = 15 if case == "member_array_shared" else 5
    assert get_contract(code).f() == expected


# A whole struct assigned into an array is copied before the target's index
# runs, so it keeps the members the index pops from.

WHOLE_SOURCES = {"local": "b", "nested": "w.inner", "ternary": "b if flag else c"}


@pytest.mark.parametrize("source", list(WHOLE_SOURCES))
def test_whole_struct_source_copied_before_index_pops(get_contract, source):
    src = WHOLE_SOURCES[source]
    popped = src.split(" ")[0]
    code = f"""
struct S:
    xs: DynArray[uint256, INF]
    n: uint256

struct W:
    tag: uint256
    inner: S

@internal
def inspect(s: S) -> uint256:
    return 0

@external
def f(flag: bool) -> (DynArray[uint256, INF], DynArray[uint256, INF], DynArray[uint256, INF]):
    a: S = S(xs=[1, 2, 3], n=5)
    b: S = a
    c: S = S(xs=[9], n=0)
    w: W = W(tag=0, inner=a)
    sarr: DynArray[S, 3] = [c, c]
    sarr[self.inspect({popped}) + {popped}.xs.pop() - 3] = {src}
    return sarr[0].xs, {popped}.xs, a.xs
    """

    assert get_contract(code).f(True) == ([1, 2, 3], [1, 2], [1, 2, 3])
