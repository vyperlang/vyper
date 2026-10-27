import pytest
from eth_abi import decode as eth_abi_decode
from eth_abi import encode as eth_abi_encode

from tests.utils import deploy_raw_returner
from vyper.compiler import compile_code
from vyper.compiler.settings import Settings
from vyper.exceptions import StructureException, TypeMismatch
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
    # the element's own length, not its address in memory
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

@external
def echo3(
    xs: DynArray[DynArray[DynArray[uint256, INF], INF], INF]
) -> DynArray[DynArray[DynArray[uint256, INF], INF], INF]:
    return xs

@external
def deep(
    xs: DynArray[DynArray[DynArray[uint256, INF], INF], INF], i: uint256, j: uint256, k: uint256
) -> uint256:
    return xs[i][j][k]
    """
    c = get_contract(code)
    assert c.echo2(NESTED) == NESTED
    assert c.inner(NESTED, 0, 2) == b"c" * 70
    assert c.inner(NESTED, 2, 0) == b"zz"
    assert c.echo5(VALUES[:3]) == VALUES[:3]
    assert c.ints([[1, 2], [], [3]], 2, 0) == 3
    deep = [[[1, 2], []], [], [[3], [4, 5, 6]]]
    assert c.echo3(deep) == deep
    assert c.deep(deep, 2, 1, 2) == 6


def test_bounded_outer_count_cap(get_contract, tx_failed):
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
    # bounded elements widen to unbounded ones
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
    # a bounded array of structs with unbounded members can itself be an
    # element, including in an internal function's return value
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
    # an internal function may return bounded elements as unbounded ones
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
    # a bounded array of unbounded elements keeps its elements when copied,
    # passed to an internal function or chosen by a ternary
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
    # writing the copy leaves the original untouched
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


def test_store_converted_value(get_contract):
    # an element built from `convert(s, Bytes[INF])` keeps its value when `s`
    # is written afterwards
    code = """
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
    """
    c = get_contract(code)
    assert c.append_converted() == [b"one"]
    assert c.store_converted() == [b"one"]
    assert c.literal_converted() == [b"one"]


def test_assigned_values_stay_independent(get_contract):
    # an element assigned from a local, or a local assigned from an element,
    # is unaffected by later writes to the other
    code = """
@internal
def _id(xs: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return xs

@external
def write_after_store(
    v: DynArray[uint256, INF]
) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
    local: DynArray[uint256, INF] = v
    xss: DynArray[DynArray[uint256, INF], INF] = [[]]
    xss[0] = local
    local[0] = 99
    return xss[0], local

@external
def write_element_copy(
    v: DynArray[uint256, INF]
) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
    xss: DynArray[DynArray[uint256, INF], INF] = [[]]
    xss[0] = self._id(v)
    ys: DynArray[uint256, INF] = xss[0]
    ys[0] = 5
    return xss[0], ys
    """
    c = get_contract(code)
    assert c.write_after_store([1, 2, 3]) == ([1, 2, 3], [99, 2, 3])
    assert c.write_element_copy([1, 2, 3]) == ([1, 2, 3], [5, 2, 3])


def test_assign_call_and_builtin_results(get_contract, env):
    # a local, struct member or element given a call or builtin result holds
    # that result
    code = """
interface I:
    def g() -> Bytes[INF]: view

struct S:
    data: Bytes[INF]

@external
def assign(
    a: address, b: address, v: Bytes[INF]
) -> (Bytes[INF], Bytes[INF], Bytes[INF], Bytes[INF]):
    x: Bytes[INF] = raw_call(a, b"", max_outsize=INF, is_static_call=True)
    s: S = S(data=b"")
    s.data = concat(x, v)
    xs: DynArray[Bytes[INF], INF] = [b"", b""]
    xs[0] = raw_call(b, b"", max_outsize=INF, is_static_call=True)
    xs[1] = slice(v, 1, 3)
    return x, s.data, xs[0], xs[1]

@external
def from_staticcalls(a: address) -> DynArray[Bytes[INF], INF]:
    xs: DynArray[Bytes[INF], INF] = [b"z", staticcall I(a).g()]
    xs.append(staticcall I(a).g())
    xs[0] = staticcall I(a).g()
    return xs
    """
    c = get_contract(code)
    a = deploy_raw_returner(env, b"\x11" * 40)
    b = deploy_raw_returner(env, b"\x22" * 7)
    expected = (b"\x11" * 40, b"\x11" * 40 + b"abcdef", b"\x22" * 7, b"bcd")
    assert c.assign(a.address, b.address, b"abcdef") == expected
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


def test_iterate_as_wider_rows(get_contract):
    # the loop variable's rows hold longer elements than the iterated ones,
    # long enough to need more memory each (Bytes[20] would not)
    code = """
@external
def total(xss: DynArray[DynArray[Bytes[10], INF], INF]) -> uint256:
    t: uint256 = 0
    for row: DynArray[Bytes[65], INF] in xss:
        for x: Bytes[65] in row:
            t += len(x)
    return t

@external
def rows(xss: DynArray[DynArray[Bytes[10], INF], INF]) -> DynArray[DynArray[Bytes[65], INF], INF]:
    ys: DynArray[DynArray[Bytes[65], INF], INF] = []
    for row: DynArray[Bytes[65], INF] in xss:
        ys.append(row)
    return ys
    """
    c = get_contract(code)
    xss = [[b"ab", b"c"], [], [b"defg", b"0123456789", b""]]
    assert c.total(xss) == 17
    assert c.rows(xss) == xss
    assert c.rows([]) == []


def test_iterate_rows_as_unbounded_rows(get_contract):
    # the loop variable is unbounded while the iterated rows have at most
    # three elements; each iteration sees its own row, and a copy of the loop
    # variable can grow without changing the iterated array
    code = """
@external
def total(xss: DynArray[DynArray[Bytes[INF], 3], INF]) -> (uint256, uint256):
    n: uint256 = 0
    t: uint256 = 0
    for row: DynArray[Bytes[INF], INF] in xss:
        n += len(row)
        for x: Bytes[INF] in row:
            t += len(x)
    return n, t

@internal
def _grow(xss: DynArray[DynArray[Bytes[INF], 3], INF]) -> DynArray[DynArray[Bytes[INF], INF], INF]:
    ys: DynArray[DynArray[Bytes[INF], INF], INF] = []
    for row: DynArray[Bytes[INF], INF] in xss:
        r: DynArray[Bytes[INF], INF] = row
        r.append(b"x")
        ys.append(r)
    return ys

@external
def grown(xss: DynArray[DynArray[Bytes[INF], 3], INF]) -> DynArray[DynArray[Bytes[INF], INF], INF]:
    return self._grow(xss)

@external
def after_growing(
    xss: DynArray[DynArray[Bytes[INF], 3], INF]
) -> DynArray[DynArray[Bytes[INF], 3], INF]:
    ys: DynArray[DynArray[Bytes[INF], INF], INF] = self._grow(xss)
    assert len(ys) == len(xss)
    return xss
    """
    c = get_contract(code)
    xss = [[b"ab", b"c" * 70], [], [b"", b"d", b"e" * 33]]
    assert c.total(xss) == (5, 106)
    assert c.total([]) == (0, 0)
    assert c.grown(xss) == [row + [b"x"] for row in xss]
    assert c.after_growing(xss) == xss


def test_iterate_bounded_bytes_as_unbounded(get_contract):
    code = """
@external
def lengths(xs: DynArray[Bytes[10], 4]) -> DynArray[uint256, 4]:
    ns: DynArray[uint256, 4] = []
    for x: Bytes[INF] in xs:
        ns.append(len(x))
    return ns

@external
def collect(xs: DynArray[Bytes[10], 4]) -> DynArray[Bytes[INF], INF]:
    ys: DynArray[Bytes[INF], INF] = []
    for x: Bytes[INF] in xs:
        ys.append(x)
    return ys

@external
def collect_local() -> DynArray[Bytes[INF], INF]:
    xs: DynArray[Bytes[10], 4] = [b"a", b"", b"0123456789"]
    ys: DynArray[Bytes[INF], INF] = []
    for x: Bytes[INF] in xs:
        ys.append(concat(x, b"!"))
    return ys

@external
def collect_strings(xs: DynArray[String[10], 4]) -> DynArray[String[INF], INF]:
    ys: DynArray[String[INF], INF] = []
    for x: String[INF] in xs:
        ys.append(x)
    return ys
    """
    c = get_contract(code)
    xs = [b"ab", b"", b"0123456789", b"z"]
    assert c.lengths(xs) == [2, 0, 10, 1]
    assert c.collect(xs) == xs
    assert c.collect([]) == []
    assert c.collect_local() == [b"a!", b"!", b"0123456789!"]
    assert c.collect_strings(["ab", "", "0123456789"]) == ["ab", "", "0123456789"]


def test_iterate_bounded_immutable_as_unbounded(get_contract):
    code = """
XS: immutable(DynArray[Bytes[10], 4])

@deploy
def __init__(xs: DynArray[Bytes[10], 4]):
    self.XS = xs

@external
def collect() -> DynArray[Bytes[INF], INF]:
    ys: DynArray[Bytes[INF], INF] = []
    for x: Bytes[INF] in self.XS:
        ys.append(x)
    return ys
    """
    xs = [b"ab", b"", b"0123456789"]
    c = get_contract(code, xs)
    assert c.collect() == xs


def test_iterate_storage_rows_as_unbounded(get_contract):
    # rows shrunk by a later store keep their old words in storage; the loop
    # variable sees only the current elements
    code = """
rows: DynArray[DynArray[uint256, 3], 4]

@external
def set_rows(xs: DynArray[DynArray[uint256, 3], 4]):
    self.rows = xs

@external
def sums() -> DynArray[uint256, 4]:
    out: DynArray[uint256, 4] = []
    for row: DynArray[uint256, INF] in self.rows:
        s: uint256 = 0
        for v: uint256 in row:
            s += v
        out.append(s)
    return out

@external
def grown() -> DynArray[DynArray[uint256, INF], INF]:
    ys: DynArray[DynArray[uint256, INF], INF] = []
    for row: DynArray[uint256, INF] in self.rows:
        r: DynArray[uint256, INF] = row
        r.append(len(row))
        ys.append(r)
    return ys
    """
    c = get_contract(code)
    c.set_rows([[1, 2, 3], [4, 5, 6], [7]])
    assert c.sums() == [6, 15, 7]
    c.set_rows([[8], []])
    assert c.sums() == [8, 0]
    assert c.grown() == [[8, 1], [0]]


def test_string_elements(get_contract):
    code = """
@external
def echo(xs: DynArray[String[INF], INF]) -> DynArray[String[INF], INF]:
    return xs

@external
def replace(
    xs: DynArray[String[INF], INF], i: uint256, v: String[INF]
) -> DynArray[String[INF], INF]:
    ys: DynArray[String[INF], INF] = xs
    ys[i] = v
    return ys

@external
def literal() -> DynArray[String[INF], INF]:
    return ["a", "", "a string longer than one thirty-two byte word"]
    """
    c = get_contract(code)
    words = ["ab", "", "c" * 70]
    assert c.echo(words) == words
    assert c.echo([]) == []
    assert c.replace(words, 1, "new" * 30) == ["ab", "new" * 30, "c" * 70]
    assert c.literal() == ["a", "", "a string longer than one thirty-two byte word"]


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
    # element is decoded into its own memory, so n elements sharing one
    # m-word tail cost O(n*m) memory
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
def f(xs: DynArray[DynArray[uint256, INF], INF]) -> uint256:
    ys: DynArray[DynArray[uint256, INF], INF] = xs
    return ys[0].pop()
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
        "Unbounded element types cannot be inferred from a wildcard",
    ),
    (
        """
interface I:
    def foo(xs: DynArray[uint256, ...][2]): nonpayable

@external
def f(a: address, x: DynArray[uint256, INF]):
    extcall I(a).foo([x, x])
        """,
        "Function arguments cannot contain unbounded sequence types inside aggregate types",
    ),
]


@pytest.mark.parametrize("code,message", REJECTED)
def test_rejected(code, message):
    with pytest.raises(StructureException) as e:
        compile_code(code, settings=Settings(experimental_codegen=True))
    assert e.value.message == message


def test_bounded_loop_variable_rejected():
    code = """
@external
def f(xs: DynArray[Bytes[INF], INF]):
    for x: Bytes[10] in xs:
        pass
    """
    with pytest.raises(TypeMismatch):
        compile_code(code, settings=Settings(experimental_codegen=True))
