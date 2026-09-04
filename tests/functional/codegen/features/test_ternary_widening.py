import pytest

from vyper.compiler import compile_code

SHORT = [b"a", b"0123456789", b""]
LONG = [b"x" * 512, b"", b"0123456789" * 20]


def test_dynarray_bytes_widening(get_contract):
    code = """
@external
def via_local(
    c: bool, a: DynArray[Bytes[10], 5], b: DynArray[Bytes[512], 5]
) -> DynArray[Bytes[512], 5]:
    ys: DynArray[Bytes[512], 5] = a if c else b
    return ys

@external
def via_return(
    c: bool, a: DynArray[Bytes[10], 5], b: DynArray[Bytes[512], 5]
) -> DynArray[Bytes[512], 5]:
    return a if c else b

@external
def via_local_flipped(
    c: bool, a: DynArray[Bytes[512], 5], b: DynArray[Bytes[10], 5]
) -> DynArray[Bytes[512], 5]:
    ys: DynArray[Bytes[512], 5] = a if c else b
    return ys

@external
def via_return_flipped(
    c: bool, a: DynArray[Bytes[512], 5], b: DynArray[Bytes[10], 5]
) -> DynArray[Bytes[512], 5]:
    return a if c else b
    """
    c = get_contract(code)
    assert c.via_local(True, SHORT, LONG) == SHORT
    assert c.via_local(False, SHORT, LONG) == LONG
    assert c.via_return(True, SHORT, LONG) == SHORT
    assert c.via_return(False, SHORT, LONG) == LONG
    assert c.via_local_flipped(True, LONG, SHORT) == LONG
    assert c.via_local_flipped(False, LONG, SHORT) == SHORT
    assert c.via_return_flipped(True, LONG, SHORT) == LONG
    assert c.via_return_flipped(False, LONG, SHORT) == SHORT


def test_dynarray_arms_of_different_widths(get_contract):
    code = """
@external
def foo(
    c: bool, a: DynArray[Bytes[10], 4], b: DynArray[Bytes[40], 4]
) -> DynArray[Bytes[512], 4]:
    return a if c else b

@external
def flipped(
    c: bool, a: DynArray[Bytes[40], 4], b: DynArray[Bytes[10], 4]
) -> DynArray[Bytes[512], 4]:
    return a if c else b
    """
    a = [b"a", b"0123456789", b"", b"xyz"]
    b = [b"q" * 40, b"", b"0123456789" * 4]
    c = get_contract(code)
    assert c.foo(True, a, b) == a
    assert c.foo(False, a, b) == b
    assert c.flipped(True, b, a) == b
    assert c.flipped(False, b, a) == a


def test_nested_dynarray_widening(get_contract):
    code = """
@external
def foo(
    c: bool, a: DynArray[DynArray[uint256, 2], 3], b: DynArray[DynArray[uint256, 4], 3]
) -> DynArray[DynArray[uint256, 4], 3]:
    return a if c else b

@external
def flipped(
    c: bool, a: DynArray[DynArray[uint256, 4], 3], b: DynArray[DynArray[uint256, 2], 3]
) -> DynArray[DynArray[uint256, 4], 3]:
    return a if c else b
    """
    a = [[1, 2], [], [3]]
    b = [[4, 5, 6, 7], [8]]
    c = get_contract(code)
    assert c.foo(True, a, b) == a
    assert c.foo(False, a, b) == b
    assert c.flipped(True, b, a) == b
    assert c.flipped(False, b, a) == a


def test_dynarray_string_widening(get_contract):
    code = """
@external
def foo(
    c: bool, a: DynArray[String[5], 3], b: DynArray[String[100], 3]
) -> DynArray[String[100], 3]:
    ys: DynArray[String[100], 3] = a if c else b
    return ys

@external
def flipped(
    c: bool, a: DynArray[String[100], 3], b: DynArray[String[5], 3]
) -> DynArray[String[100], 3]:
    ys: DynArray[String[100], 3] = a if c else b
    return ys
    """
    a = ["hello", "", "hi"]
    b = ["0123456789" * 10, "x"]
    c = get_contract(code)
    assert c.foo(True, a, b) == a
    assert c.foo(False, a, b) == b
    assert c.flipped(True, b, a) == b
    assert c.flipped(False, b, a) == a


def test_static_array_of_dynarray_widening(get_contract):
    code = """
@external
def foo(
    c: bool, a: DynArray[uint256, 2][2], b: DynArray[uint256, 4][2]
) -> DynArray[uint256, 4][2]:
    return a if c else b

@external
def flipped(
    c: bool, a: DynArray[uint256, 4][2], b: DynArray[uint256, 2][2]
) -> DynArray[uint256, 4][2]:
    return a if c else b
    """
    a = [[1, 2], [3]]
    b = [[4, 5, 6, 7], [8]]
    c = get_contract(code)
    assert c.foo(True, a, b) == a
    assert c.foo(False, a, b) == b
    assert c.flipped(True, b, a) == b
    assert c.flipped(False, b, a) == a


def _ternaries(ir_node, source):
    if ir_node.value == "if" and ir_node.annotation == source:
        yield ir_node
    for arg in ir_node.args:
        yield from _ternaries(arg, source)


def test_same_type_ternary(get_contract, compiler_settings, experimental_codegen):
    code = """
@external
def foo(
    c: bool, a: DynArray[Bytes[512], 5], b: DynArray[Bytes[512], 5]
) -> DynArray[Bytes[512], 5]:
    ys: DynArray[Bytes[512], 5] = a if c else b
    return ys

@external
def bar(c: bool, a: DynArray[uint256, 2], b: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    return a if c else b
    """
    c = get_contract(code)
    assert c.foo(True, SHORT, LONG) == SHORT
    assert c.foo(False, SHORT, LONG) == LONG
    assert c.bar(True, [1, 2], [3, 4, 5, 6, 7]) == [1, 2]
    assert c.bar(False, [1, 2], [3, 4, 5, 6, 7]) == [3, 4, 5, 6, 7]

    # the arms already have the element layout of the result, so neither
    # arm is converted element by element
    ir = compile_code(code, output_formats=["ir_runtime"], settings=compiler_settings)
    ir = ir["ir_runtime"]
    if experimental_codegen:
        assert "typed_dyn_copy" not in str(ir)
    else:
        ternaries = list(_ternaries(ir, "a if c else b"))
        assert len(ternaries) == 2
        for ternary in ternaries:
            _, body, orelse = ternary.args
            # each arm is the variable itself, not a copy of it
            assert body.is_literal
            assert orelse.is_literal


def test_bytestring_ternary(get_contract):
    code = """
@external
def foo(c: bool, a: Bytes[10], b: Bytes[20]) -> Bytes[20]:
    return a if c else b

@external
def bar(c: bool, a: String[3], b: String[64]) -> String[64]:
    s: String[64] = a if c else b
    return s

@external
def foo_flipped(c: bool, a: Bytes[20], b: Bytes[10]) -> Bytes[20]:
    return a if c else b

@external
def bar_flipped(c: bool, a: String[64], b: String[3]) -> String[64]:
    s: String[64] = a if c else b
    return s
    """
    c = get_contract(code)
    assert c.foo(True, b"0123456789", b"x" * 20) == b"0123456789"
    assert c.foo(False, b"0123456789", b"x" * 20) == b"x" * 20
    assert c.bar(True, "abc", "y" * 64) == "abc"
    assert c.bar(False, "abc", "y" * 64) == "y" * 64
    assert c.foo_flipped(True, b"x" * 20, b"0123456789") == b"x" * 20
    assert c.foo_flipped(False, b"x" * 20, b"0123456789") == b"0123456789"
    assert c.bar_flipped(True, "y" * 64, "abc") == "y" * 64
    assert c.bar_flipped(False, "y" * 64, "abc") == "abc"


def test_ternary_as_event_argument(get_contract, get_logs):
    code = """
event Picked:
    xs: DynArray[Bytes[512], 5]

@external
def foo(c: bool, a: DynArray[Bytes[10], 5], b: DynArray[Bytes[512], 5]):
    log Picked(xs=a if c else b)

@external
def flipped(c: bool, a: DynArray[Bytes[512], 5], b: DynArray[Bytes[10], 5]):
    log Picked(xs=a if c else b)
    """
    c = get_contract(code)

    c.foo(True, SHORT, LONG)
    (log,) = get_logs(c, "Picked")
    assert log.args.xs == SHORT

    c.foo(False, SHORT, LONG)
    (log,) = get_logs(c, "Picked")
    assert log.args.xs == LONG

    c.flipped(True, LONG, SHORT)
    (log,) = get_logs(c, "Picked")
    assert log.args.xs == LONG

    c.flipped(False, LONG, SHORT)
    (log,) = get_logs(c, "Picked")
    assert log.args.xs == SHORT


def test_tuple_ternary(get_contract):
    code = """
@internal
def _short(a: Bytes[10]) -> (Bytes[10], uint256):
    return a, 1

@internal
def _long(b: Bytes[40]) -> (Bytes[40], uint256):
    return b, 2

@external
def from_calls(c: bool, a: Bytes[10], b: Bytes[40]) -> (Bytes[40], uint256):
    return self._short(a) if c else self._long(b)

@external
def from_locals(c: bool, a: Bytes[10], b: Bytes[40]) -> (Bytes[40], uint256):
    x: (Bytes[10], uint256) = (a, 1)
    y: (Bytes[40], uint256) = (b, 2)
    return x if c else y

@external
def from_calls_flipped(c: bool, a: Bytes[40], b: Bytes[10]) -> (Bytes[40], uint256):
    return self._long(a) if c else self._short(b)

@external
def from_locals_flipped(c: bool, a: Bytes[40], b: Bytes[10]) -> (Bytes[40], uint256):
    x: (Bytes[40], uint256) = (a, 2)
    y: (Bytes[10], uint256) = (b, 1)
    return x if c else y
    """
    c = get_contract(code)
    assert c.from_calls(True, b"abc", b"x" * 40) == (b"abc", 1)
    assert c.from_calls(False, b"abc", b"x" * 40) == (b"x" * 40, 2)
    assert c.from_locals(True, b"abc", b"x" * 40) == (b"abc", 1)
    assert c.from_locals(False, b"abc", b"x" * 40) == (b"x" * 40, 2)
    assert c.from_calls_flipped(True, b"x" * 40, b"abc") == (b"x" * 40, 2)
    assert c.from_calls_flipped(False, b"x" * 40, b"abc") == (b"abc", 1)
    assert c.from_locals_flipped(True, b"x" * 40, b"abc") == (b"x" * 40, 2)
    assert c.from_locals_flipped(False, b"x" * 40, b"abc") == (b"abc", 1)


def test_tuple_with_unbounded_member_ternary(get_contract, experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")

    code = """
@internal
def _short(a: DynArray[Bytes[10], 5]) -> (DynArray[uint256, INF], DynArray[Bytes[10], 5]):
    return ([1, 2], a)

@internal
def _long(b: DynArray[Bytes[512], 5]) -> (DynArray[uint256, INF], DynArray[Bytes[512], 5]):
    return ([3], b)

@external
def whole(
    c: bool, a: DynArray[Bytes[10], 5], b: DynArray[Bytes[512], 5]
) -> (DynArray[uint256, INF], DynArray[Bytes[512], 5]):
    return self._short(a) if c else self._long(b)

@external
def whole_flipped(
    c: bool, a: DynArray[Bytes[512], 5], b: DynArray[Bytes[10], 5]
) -> (DynArray[uint256, INF], DynArray[Bytes[512], 5]):
    return self._long(a) if c else self._short(b)

@external
def member(
    c: bool, a: DynArray[Bytes[10], 5], b: DynArray[Bytes[512], 5]
) -> DynArray[Bytes[512], 5]:
    return (self._short(a) if c else self._long(b))[1]

@external
def member_flipped(
    c: bool, a: DynArray[Bytes[512], 5], b: DynArray[Bytes[10], 5]
) -> DynArray[Bytes[512], 5]:
    return (self._long(a) if c else self._short(b))[1]
    """
    c = get_contract(code)
    assert c.whole(True, SHORT, LONG) == ([1, 2], SHORT)
    assert c.whole(False, SHORT, LONG) == ([3], LONG)
    assert c.whole_flipped(True, LONG, SHORT) == ([3], LONG)
    assert c.whole_flipped(False, LONG, SHORT) == ([1, 2], SHORT)
    assert c.member(True, SHORT, LONG) == SHORT
    assert c.member(False, SHORT, LONG) == LONG
    assert c.member_flipped(True, LONG, SHORT) == LONG
    assert c.member_flipped(False, LONG, SHORT) == SHORT


def test_tuple_with_unbounded_member_nested_ternary(get_contract, experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")

    code = """
@internal
def _short(
    a: DynArray[DynArray[uint256, 2], 3]
) -> (DynArray[uint256, INF], DynArray[DynArray[uint256, 2], 3]):
    return ([1], a)

@internal
def _long(
    b: DynArray[DynArray[uint256, 4], 3]
) -> (DynArray[uint256, INF], DynArray[DynArray[uint256, 4], 3]):
    return ([2], b)

@external
def whole(
    c: bool, a: DynArray[DynArray[uint256, 2], 3], b: DynArray[DynArray[uint256, 4], 3]
) -> (DynArray[uint256, INF], DynArray[DynArray[uint256, 4], 3]):
    return self._short(a) if c else self._long(b)

@external
def member_flipped(
    c: bool, a: DynArray[DynArray[uint256, 4], 3], b: DynArray[DynArray[uint256, 2], 3]
) -> DynArray[DynArray[uint256, 4], 3]:
    return (self._long(a) if c else self._short(b))[1]
    """
    a = [[1, 2], [3], []]
    b = [[4, 5, 6, 7], [], [8]]
    c = get_contract(code)
    assert c.whole(True, a, b) == ([1], a)
    assert c.whole(False, a, b) == ([2], b)
    assert c.member_flipped(True, b, a) == b
    assert c.member_flipped(False, b, a) == a
