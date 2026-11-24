import pytest
from eth_abi import encode as eth_abi_encode

from vyper.utils import method_id


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


BATCH = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]
"""

OWNER = "0x" + "12" * 20

_HOLDER = BATCH + """
struct Holder:
    bs: DynArray[Batch, INF]
    n: uint256
"""
_HOLDER_ABI = "((address,uint256[])[],uint256)"

_ROWS_ABI = "(address,uint256[])[]"

_ARRAY_BOUNDS = ("3", "INF")


@pytest.mark.parametrize("inlining", [True, False])
def test_struct_return_with_stack_and_memory_arguments(
    get_contract, compiler_settings, no_inlining_settings, inlining
):
    code = """
struct S:
    a: DynArray[uint256, INF]
    b: DynArray[uint256, INF]
    c: DynArray[uint256, INF]
    tag: uint256

@internal
def build(a: uint256, b: uint256, c: uint256, d: uint256,
          e: uint256, f: uint256, tag: uint256) -> S:
    return S(a=[a, b], b=[c, d], c=[e, f], tag=tag)

@external
def f() -> uint256[17]:
    first: S = self.build(1, 2, 3, 4, 5, 6, 7)
    second: S = self.build(8, 9, 10, 11, 12, 13, 14)
    first.c.append(99)
    return [first.a[0], first.a[1], first.b[0], first.b[1],
            first.c[0], first.c[1], first.tag,
            second.a[0], second.a[1], second.b[0], second.b[1],
            second.c[0], second.c[1], second.tag,
            first.c[2], len(first.c), len(second.c)]
"""
    settings = compiler_settings if inlining else no_inlining_settings
    c = get_contract(code, compiler_settings=settings)
    assert c.f() == list(range(1, 15)) + [99, 3, 2]


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


# Internal returns of a value holding an array of such structs: the callee
# packs the value and every payload it reaches into one buffer, the caller
# rebases the pointers. Most tests call each producer `g` twice from one
# external function (a payload left in the callee frame is overwritten by the
# second call); two call sites keep `g` out of line, so their `inlining`
# param only toggles whether the helper `mk` is inlined into `g`. A single
# call site is inlined (at -O gas and codesize), which puts the pack and the
# rebase in one function; `test_internal_return_of_struct_array_single_call`
# covers that.
_MK = """
@internal
def mk(i: uint256, m: uint256, seed: uint256) -> Batch:
    vs: DynArray[uint256, INF] = []
    for j: uint256 in range(m, bound=40):
        vs.append(seed + i * 100 + j)
    return Batch(owner=convert(seed + i, address), values=vs)
"""

_OUTER_WITH_NOTE = BATCH + """
struct Outer:
    tag: uint256
    batches: DynArray[Batch, 5]
    note: Bytes[INF]
"""
_OUTER_WITH_NOTE_ABI = "(uint256,(address,uint256[])[],bytes)"

# (declarations, return type, abi type, body of `g(n, m, seed, note)`)
_PRODUCERS = {
    "array_3": (
        BATCH,
        "DynArray[Batch, 3]",
        _ROWS_ABI,
        """
    xs: DynArray[Batch, 3] = []
    for i: uint256 in range(n, bound=3):
        xs.append(self.mk(i, m, seed))
    return xs
""",
    ),
    "array_inf": (
        BATCH,
        "DynArray[Batch, INF]",
        _ROWS_ABI,
        """
    xs: DynArray[Batch, INF] = []
    for i: uint256 in range(n, bound=3):
        xs.append(self.mk(i, m, seed))
    return xs
""",
    ),
    "outer": (
        _OUTER_WITH_NOTE,
        "Outer",
        _OUTER_WITH_NOTE_ABI,
        """
    o: Outer = Outer(tag=seed, batches=[], note=note)
    for i: uint256 in range(n, bound=3):
        o.batches.append(self.mk(i, m, seed))
    return o
""",
    ),
    "holder": (
        _HOLDER,
        "Holder",
        _HOLDER_ABI,
        """
    # appending grows `h.bs` in place, so its payload has spare room
    h: Holder = Holder(bs=[], n=seed)
    for i: uint256 in range(n, bound=3):
        h.bs.append(self.mk(i, m, seed))
    return h
""",
    ),
    "outer_array": (
        _OUTER_WITH_NOTE,
        "DynArray[Outer, 2]",
        f"{_OUTER_WITH_NOTE_ABI}[]",
        """
    os: DynArray[Outer, 2] = []
    for k: uint256 in range(2):
        o: Outer = Outer(tag=seed + k, batches=[], note=note)
        for i: uint256 in range(n, bound=3):
            o.batches.append(self.mk(i, m, seed + k))
        os.append(o)
    return os
""",
    ),
    # payloads that hold cells of further payloads
    "holder_array": (
        _HOLDER,
        "DynArray[Holder, 2]",
        f"{_HOLDER_ABI}[]",
        """
    hs: DynArray[Holder, 2] = []
    for k: uint256 in range(2):
        h: Holder = Holder(bs=[], n=seed + k)
        for i: uint256 in range(n, bound=3):
            h.bs.append(self.mk(i, m, seed + k))
        hs.append(h)
    return hs
""",
    ),
}


def _mk_rows(n, m, seed):
    return [("0x" + f"{seed + i:040x}", [seed + i * 100 + j for j in range(m)]) for i in range(n)]


def _produced(shape, n, m, seed, note):
    # Each shape has its own ABI type, so its expected tuple/list layout differs.
    if shape in ("array_3", "array_inf"):
        return _mk_rows(n, m, seed)
    if shape == "outer":
        return (seed, _mk_rows(n, m, seed), note)
    if shape == "holder":
        return (_mk_rows(n, m, seed), seed)
    if shape == "outer_array":
        return [(seed + k, _mk_rows(n, m, seed + k), note) for k in range(2)]
    assert shape == "holder_array"
    return [(_mk_rows(n, m, seed + k), seed + k) for k in range(2)]


def _producer_code(shape, external_body):
    # `enc` keeps a single copy of the encoder, which at -O none is large
    # enough for two copies to exceed EIP-170 for the nested shapes
    decls, ret, _, body = _PRODUCERS[shape]
    return (
        decls
        + _MK
        + f"""
@internal
def enc(x: {ret}) -> Bytes[INF]:
    return abi_encode(x)

@internal
def g(n: uint256, m: uint256, seed: uint256, note: Bytes[INF]) -> {ret}:"""
        + body
        + external_body.format(ret=ret)
    )


@pytest.mark.parametrize("inlining", [True, False])
@pytest.mark.parametrize("shape", _PRODUCERS.keys())
def test_internal_return_of_struct_array_survives_second_call(
    get_contract, compiler_settings, no_inlining_settings, shape, inlining
):
    code = _producer_code(
        shape,
        """
@external
def f(n: uint256, m: uint256, note: Bytes[INF]) -> (Bytes[INF], Bytes[INF]):
    first: {ret} = self.g(n, m, 1, note)
    second: {ret} = self.g(n, m, 99, b"zz")
    return self.enc(first), self.enc(second)
""",
    )

    settings = compiler_settings if inlining else no_inlining_settings
    c = get_contract(code, compiler_settings=settings)
    abi = _PRODUCERS[shape][2]
    for n in (0, 1, 3):
        for m in (0, 1, 40):
            note = b"q" * m
            first = eth_abi_encode([abi], [_produced(shape, n, m, 1, note)])
            second = eth_abi_encode([abi], [_produced(shape, n, m, 99, b"zz")])
            assert c.f(n, m, note) == (first, second), (n, m)


@pytest.mark.parametrize("shape", _PRODUCERS.keys())
def test_internal_return_of_struct_array_returned_externally(env, get_contract, shape):
    code = _producer_code(
        shape,
        """
@external
def f() -> {ret}:
    first: {ret} = self.g(3, 2, 1, b"note")
    second: {ret} = self.g(1, 1, 99, b"zz")
    return first
""",
    )

    c = get_contract(code)
    abi = _PRODUCERS[shape][2]
    expected = eth_abi_encode([abi], [_produced(shape, 3, 2, 1, b"note")])
    assert env.message_call(c.address, data=method_id("f()")) == expected


@pytest.mark.parametrize("shape", _PRODUCERS.keys())
def test_internal_return_of_struct_array_single_call(env, get_contract, shape):
    code = _producer_code(
        shape,
        """
@external
def f(n: uint256, m: uint256, note: Bytes[INF]) -> {ret}:
    return self.g(n, m, 1, note)
""",
    )

    c = get_contract(code)
    abi = _PRODUCERS[shape][2]
    for n in (0, 1, 3):
        for m in (0, 1, 40):
            note = b"q" * m
            args = eth_abi_encode(["uint256", "uint256", "bytes"], [n, m, note])
            out = env.message_call(c.address, data=method_id("f(uint256,uint256,bytes)") + args)
            assert out == eth_abi_encode([abi], [_produced(shape, n, m, 1, note)]), (n, m)


# (shape, writes after both calls, expected first, expected second) where
# `first` and `second` are the two returned values and `c` a copy of an
# element of `first`; every write lands in `first` or `c` only
_ROWS_1 = _mk_rows(2, 2, 1)
_ROWS_99 = _mk_rows(2, 2, 99)
_GROWN = (_ROWS_1[0][0], _ROWS_1[0][1] + [7])

_MUTATIONS = [
    (
        "array_3",
        """
    c: Batch = first[0]
    c.values.append(7)
    first.append(c)
    first[1] = second[0]
""",
        [_ROWS_1[0], _ROWS_99[0], _GROWN],
        _ROWS_99,
    ),
    (
        "array_inf",
        """
    c: Batch = first[0]
    c.values.append(7)
    first.append(c)
    first[1] = second[0]
    first.pop()
    first.append(c)
""",
        [_ROWS_1[0], _ROWS_99[0], _GROWN],
        _ROWS_99,
    ),
    (
        "outer",
        """
    c: Batch = first.batches[0]
    c.values.append(7)
    first.batches.append(c)
    first.batches[1] = second.batches[0]
    first.note = b"new"
""",
        (1, [_ROWS_1[0], _ROWS_99[0], _GROWN], b"new"),
        (99, _ROWS_99, b"zz"),
    ),
    (
        "holder",
        """
    c: Batch = first.bs[0]
    c.values.append(7)
    first.bs.append(c)
    first.bs[1] = second.bs[0]
""",
        ([_ROWS_1[0], _ROWS_99[0], _GROWN], 1),
        (_ROWS_99, 99),
    ),
    (
        "outer_array",
        """
    c: Batch = first[0].batches[0]
    c.values.append(7)
    o: Outer = first[1]
    o.batches.append(c)
    first[0] = o
""",
        [(2, _mk_rows(2, 2, 2) + [_GROWN], b"n"), (2, _mk_rows(2, 2, 2), b"n")],
        [(99, _ROWS_99, b"zz"), (100, _mk_rows(2, 2, 100), b"zz")],
    ),
]


@pytest.mark.parametrize("inlining", [True, False])
@pytest.mark.parametrize(
    "shape,writes,expected_first,expected_second", _MUTATIONS, ids=[m[0] for m in _MUTATIONS]
)
def test_internal_return_of_struct_array_then_mutate(
    get_contract,
    compiler_settings,
    no_inlining_settings,
    shape,
    writes,
    expected_first,
    expected_second,
    inlining,
):
    code = _producer_code(
        shape,
        """
@external
def f() -> (Bytes[INF], Bytes[INF]):
    first: {ret} = self.g(2, 2, 1, b"n")
    second: {ret} = self.g(2, 2, 99, b"zz")
"""
        + writes.replace("{", "{{").replace("}", "}}")
        + """
    return self.enc(first), self.enc(second)
""",
    )

    settings = compiler_settings if inlining else no_inlining_settings
    c = get_contract(code, compiler_settings=settings)
    abi = _PRODUCERS[shape][2]
    expected = (eth_abi_encode([abi], [expected_first]), eth_abi_encode([abi], [expected_second]))
    assert c.f() == expected


# The returned value is the callee's argument: the packed copy is
# independent of the caller's source.
@pytest.mark.parametrize("inlining", [True, False])
@pytest.mark.parametrize("bound", _ARRAY_BOUNDS)
def test_internal_return_of_struct_array_arg(
    get_contract, compiler_settings, no_inlining_settings, bound, inlining
):
    code = BATCH + f"""
@internal
def ident(xs: DynArray[Batch, {bound}]) -> DynArray[Batch, {bound}]:
    return xs

@external
def f(xs: DynArray[Batch, {bound}], ys: DynArray[Batch, {bound}]) -> (
    Bytes[INF], Bytes[INF], Bytes[INF]
):
    src: DynArray[Batch, {bound}] = xs
    first: DynArray[Batch, {bound}] = self.ident(src)
    second: DynArray[Batch, {bound}] = self.ident(ys)
    c: Batch = first[0]
    c.values.append(7)
    first[0] = c
    src.pop()
    return abi_encode(src), abi_encode(first), abi_encode(second)
    """

    settings = compiler_settings if inlining else no_inlining_settings
    c = get_contract(code, compiler_settings=settings)
    xs = [(OWNER, [1, 2]), (OWNER, [3])]
    ys = [("0x" + "99" * 20, [9, 9, 9])]

    def enc(rows):
        return eth_abi_encode([_ROWS_ABI], [rows])

    expected = (enc(xs[:1]), enc([(OWNER, [1, 2, 7]), (OWNER, [3])]), enc(ys))
    assert c.f(xs, ys) == expected


# The callee stores into its argument before returning it, so two elements
# share one payload and another element's payload has spare room; the packed
# value holds a separate copy of each.
@pytest.mark.parametrize("inlining", [True, False])
def test_internal_return_of_element_wise_mutated_array(
    get_contract, compiler_settings, no_inlining_settings, inlining
):
    code = BATCH + """
@internal
def g(xs: DynArray[Batch, 3], b: Batch) -> DynArray[Batch, 3]:
    xs[0] = b
    xs[1] = b
    grown: Batch = b
    grown.values.append(5)
    grown.values.append(6)
    xs[2] = grown
    return xs

@external
def f(xs: DynArray[Batch, 3], b: Batch) -> (Bytes[INF], Bytes[INF]):
    first: DynArray[Batch, 3] = self.g(xs, b)
    second: DynArray[Batch, 3] = self.g(xs, Batch(owner=self, values=[]))
    c: Batch = first[0]
    c.values.append(7)
    first[1] = c
    return abi_encode(first), abi_encode(second)
    """

    settings = compiler_settings if inlining else no_inlining_settings
    c = get_contract(code, compiler_settings=settings)
    xs = [(OWNER, [1]), (OWNER, [2]), (OWNER, [3])]
    b = ("0x" + "44" * 20, [8, 9])
    empty = (c.address, [])
    first = [b, (b[0], [8, 9, 7]), (b[0], [8, 9, 5, 6])]
    second = [empty, empty, (c.address, [5, 6])]
    expected = (eth_abi_encode([_ROWS_ABI], [first]), eth_abi_encode([_ROWS_ABI], [second]))
    assert c.f(xs, b) == expected
