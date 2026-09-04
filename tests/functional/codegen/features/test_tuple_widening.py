import pytest

# a tuple can be assigned to a tuple with wider members, e.g.
# (Bytes[10], uint256) to (Bytes[40], uint256). the two have different
# memory layouts (the second member sits at a different offset), so the
# assignment must copy member by member rather than as a flat block.

VALUES = [(b"abc", 3, "hello"), (b"0123456789", 2**200, ""), (b"", 0, "hi")]


@pytest.mark.parametrize("a,n,s", VALUES)
def test_local_assignment(get_contract, a, n, s):
    code = """
@external
def declared(a: Bytes[10], n: uint256, s: String[5]) -> (Bytes[40], uint256, String[64]):
    x: (Bytes[10], uint256, String[5]) = (a, n, s)
    y: (Bytes[40], uint256, String[64]) = x
    return y

@external
def assigned(a: Bytes[10], n: uint256, s: String[5]) -> (Bytes[40], uint256, String[64]):
    x: (Bytes[10], uint256, String[5]) = (a, n, s)
    y: (Bytes[40], uint256, String[64]) = (b"", 0, "")
    y = x
    return y

@external
def members(a: Bytes[10], n: uint256, s: String[5]) -> (uint256, String[64], Bytes[40]):
    x: (Bytes[10], uint256, String[5]) = (a, n, s)
    y: (Bytes[40], uint256, String[64]) = x
    return y[1], y[2], y[0]
    """
    c = get_contract(code)
    assert c.declared(a, n, s) == (a, n, s)
    assert c.assigned(a, n, s) == (a, n, s)
    assert c.members(a, n, s) == (n, s, a)


@pytest.mark.parametrize("a,n,s", VALUES)
def test_return_widening(get_contract, a, n, s):
    code = """
@internal
def _narrow(a: Bytes[10], n: uint256, s: String[5]) -> (Bytes[40], uint256, String[64]):
    x: (Bytes[10], uint256, String[5]) = (a, n, s)
    return x

@external
def via_internal(a: Bytes[10], n: uint256, s: String[5]) -> (Bytes[40], uint256, String[64]):
    return self._narrow(a, n, s)

@external
def via_internal_local(a: Bytes[10], n: uint256, s: String[5]) -> (uint256, String[64], Bytes[40]):
    y: (Bytes[40], uint256, String[64]) = self._narrow(a, n, s)
    return y[1], y[2], y[0]

@external
def via_external(a: Bytes[10], n: uint256, s: String[5]) -> (Bytes[40], uint256, String[64]):
    x: (Bytes[10], uint256, String[5]) = (a, n, s)
    return x
    """
    c = get_contract(code)
    assert c.via_internal(a, n, s) == (a, n, s)
    assert c.via_internal_local(a, n, s) == (n, s, a)
    assert c.via_external(a, n, s) == (a, n, s)


@pytest.mark.parametrize("a,n,s", VALUES)
def test_internal_call_argument(get_contract, a, n, s):
    code = """
@internal
def _members(t: (Bytes[40], uint256, String[64])) -> (uint256, String[64], Bytes[40]):
    return t[1], t[2], t[0]

@internal
def _whole(t: (Bytes[40], uint256, String[64])) -> (Bytes[40], uint256, String[64]):
    return t

@external
def members(a: Bytes[10], n: uint256, s: String[5]) -> (uint256, String[64], Bytes[40]):
    x: (Bytes[10], uint256, String[5]) = (a, n, s)
    return self._members(x)

@external
def whole(a: Bytes[10], n: uint256, s: String[5]) -> (Bytes[40], uint256, String[64]):
    x: (Bytes[10], uint256, String[5]) = (a, n, s)
    return self._whole(x)
    """
    c = get_contract(code)
    assert c.members(a, n, s) == (n, s, a)
    assert c.whole(a, n, s) == (a, n, s)


@pytest.mark.parametrize("a,n,s", VALUES)
def test_struct_member_widening(get_contract, a, n, s):
    code = """
struct Rec:
    t: (Bytes[40], uint256, String[64])
    n: uint256

@external
def foo(a: Bytes[10], n: uint256, s: String[5]) -> ((Bytes[40], uint256, String[64]), uint256):
    x: (Bytes[10], uint256, String[5]) = (a, n, s)
    r: Rec = Rec(t=x, n=n + 1)
    return r.t, r.n

@external
def members(a: Bytes[10], n: uint256, s: String[5]) -> (uint256, String[64], Bytes[40], uint256):
    x: (Bytes[10], uint256, String[5]) = (a, n, s)
    r: Rec = Rec(t=x, n=n + 1)
    return r.t[1], r.t[2], r.t[0], r.n
    """
    c = get_contract(code)
    assert c.foo(a, n, s) == ((a, n, s), n + 1)
    assert c.members(a, n, s) == (n, s, a, n + 1)


@pytest.mark.parametrize("a,n,s", VALUES)
def test_nested_tuple_widening(get_contract, a, n, s):
    code = """
@external
def foo(a: Bytes[10], n: uint256, s: String[5]) -> ((Bytes[40], uint256), String[64], uint256):
    x: ((Bytes[10], uint256), String[5], uint256) = ((a, n), s, n + 1)
    y: ((Bytes[40], uint256), String[64], uint256) = x
    return y

@external
def unpack(a: Bytes[10], n: uint256, s: String[5]) -> (uint256, String[64], Bytes[40], uint256):
    x: ((Bytes[10], uint256), String[5], uint256) = ((a, n), s, n + 1)
    inner: (Bytes[40], uint256) = (b"", 0)
    t: String[64] = ""
    m: uint256 = 0
    inner, t, m = x
    return inner[1], t, inner[0], m
    """
    c = get_contract(code)
    assert c.foo(a, n, s) == ((a, n), s, n + 1)
    assert c.unpack(a, n, s) == (n, s, a, n + 1)


def test_dynarray_member_widening(get_contract):
    code = """
@external
def elements(xs: DynArray[Bytes[10], 2], n: uint256) -> (DynArray[Bytes[40], 2], uint256):
    x: (DynArray[Bytes[10], 2], uint256) = (xs, n)
    y: (DynArray[Bytes[40], 2], uint256) = x
    return y

@external
def capacity(xs: DynArray[uint256, 2], a: Bytes[10]) -> (DynArray[uint256, 4], Bytes[40], uint256):
    x: (DynArray[uint256, 2], Bytes[10], uint256) = (xs, a, 7)
    y: (DynArray[uint256, 4], Bytes[40], uint256) = x
    return y

@external
def nested(
    xs: DynArray[DynArray[uint256, 2], 2], a: Bytes[10]
) -> (DynArray[DynArray[uint256, 3], 2], Bytes[40]):
    x: (DynArray[DynArray[uint256, 2], 2], Bytes[10]) = (xs, a)
    y: (DynArray[DynArray[uint256, 3], 2], Bytes[40]) = x
    return y
    """
    c = get_contract(code)
    assert c.elements([b"abc", b"0123456789"], 3) == ([b"abc", b"0123456789"], 3)
    assert c.elements([], 3) == ([], 3)
    assert c.capacity([1, 2], b"abc") == ([1, 2], b"abc", 7)
    assert c.capacity([], b"") == ([], b"", 7)
    assert c.nested([[1, 2], [3]], b"abc") == ([[1, 2], [3]], b"abc")
    assert c.nested([[], []], b"abc") == ([[], []], b"abc")


@pytest.mark.parametrize("a,n,s", VALUES)
def test_state_variable_widening(get_contract, a, n, s):
    code = """
x: (Bytes[40], uint256, String[64])
Y: immutable((Bytes[40], uint256, String[64]))

@deploy
def __init__(a: Bytes[10], n: uint256, s: String[5]):
    y: (Bytes[10], uint256, String[5]) = (a, n, s)
    Y = y

@external
def set_x(a: Bytes[10], n: uint256, s: String[5]):
    t: (Bytes[10], uint256, String[5]) = (a, n, s)
    self.x = t

@external
def get_x() -> (Bytes[40], uint256, String[64]):
    return self.x

@external
def get_x_members() -> (uint256, String[64], Bytes[40]):
    return self.x[1], self.x[2], self.x[0]

@external
def get_y() -> (Bytes[40], uint256, String[64]):
    return Y
    """
    c = get_contract(code, a, n, s)
    assert c.get_y() == (a, n, s)
    c.set_x(a, n, s)
    assert c.get_x() == (a, n, s)
    assert c.get_x_members() == (n, s, a)


@pytest.mark.parametrize("a,n,s", VALUES)
def test_unbounded_member_nested_tuple_widening(get_contract, experimental_codegen, a, n, s):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")

    code = """
@internal
def _narrow(
    a: Bytes[10], n: uint256, s: String[5]
) -> ((Bytes[10], uint256, String[5]), DynArray[uint256, INF]):
    return ((a, n, s), [n, 1])

@internal
def _wide(
    a: Bytes[10], n: uint256, s: String[5]
) -> ((Bytes[40], uint256, String[64]), DynArray[uint256, INF]):
    return self._narrow(a, n, s)

@external
def foo(
    a: Bytes[10], n: uint256, s: String[5]
) -> ((Bytes[40], uint256, String[64]), DynArray[uint256, INF]):
    return self._wide(a, n, s)

@external
def members(a: Bytes[10], n: uint256, s: String[5]) -> (uint256, String[64], Bytes[40]):
    t: (Bytes[40], uint256, String[64]) = self._wide(a, n, s)[0]
    return t[1], t[2], t[0]
    """
    c = get_contract(code)
    assert c.foo(a, n, s) == ((a, n, s), [n, 1])
    assert c.members(a, n, s) == (n, s, a)
