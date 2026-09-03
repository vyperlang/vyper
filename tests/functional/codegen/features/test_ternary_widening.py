import pytest

from vyper.compiler import compile_code


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("requires --experimental-codegen")


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
    """
    c = get_contract(code)
    assert c.via_local(True, SHORT, LONG) == SHORT
    assert c.via_local(False, SHORT, LONG) == LONG
    assert c.via_return(True, SHORT, LONG) == SHORT
    assert c.via_return(False, SHORT, LONG) == LONG


def test_dynarray_arms_of_different_widths(get_contract):
    code = """
@external
def foo(
    c: bool, a: DynArray[Bytes[10], 4], b: DynArray[Bytes[40], 4]
) -> DynArray[Bytes[512], 4]:
    return a if c else b
    """
    a = [b"a", b"0123456789", b"", b"xyz"]
    b = [b"q" * 40, b"", b"0123456789" * 4]
    c = get_contract(code)
    assert c.foo(True, a, b) == a
    assert c.foo(False, a, b) == b


def test_nested_dynarray_widening(get_contract):
    code = """
@external
def foo(
    c: bool, a: DynArray[DynArray[uint256, 2], 3], b: DynArray[DynArray[uint256, 4], 3]
) -> DynArray[DynArray[uint256, 4], 3]:
    return a if c else b
    """
    a = [[1, 2], [], [3]]
    b = [[4, 5, 6, 7], [8]]
    c = get_contract(code)
    assert c.foo(True, a, b) == a
    assert c.foo(False, a, b) == b


def test_dynarray_string_widening(get_contract):
    code = """
@external
def foo(
    c: bool, a: DynArray[String[5], 3], b: DynArray[String[100], 3]
) -> DynArray[String[100], 3]:
    ys: DynArray[String[100], 3] = a if c else b
    return ys
    """
    a = ["hello", "", "hi"]
    b = ["0123456789" * 10, "x"]
    c = get_contract(code)
    assert c.foo(True, a, b) == a
    assert c.foo(False, a, b) == b


def test_static_array_of_dynarray_widening(get_contract):
    code = """
@external
def foo(
    c: bool, a: DynArray[uint256, 2][2], b: DynArray[uint256, 4][2]
) -> DynArray[uint256, 4][2]:
    return a if c else b
    """
    a = [[1, 2], [3]]
    b = [[4, 5, 6, 7], [8]]
    c = get_contract(code)
    assert c.foo(True, a, b) == a
    assert c.foo(False, a, b) == b


def test_same_type_ternary(get_contract, compiler_settings):
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
    assert "typed_dyn_copy" not in str(ir["ir_runtime"])


def test_bytestring_ternary(get_contract):
    code = """
@external
def foo(c: bool, a: Bytes[10], b: Bytes[20]) -> Bytes[20]:
    return a if c else b

@external
def bar(c: bool, a: String[3], b: String[64]) -> String[64]:
    s: String[64] = a if c else b
    return s
    """
    c = get_contract(code)
    assert c.foo(True, b"0123456789", b"x" * 20) == b"0123456789"
    assert c.foo(False, b"0123456789", b"x" * 20) == b"x" * 20
    assert c.bar(True, "abc", "y" * 64) == "abc"
    assert c.bar(False, "abc", "y" * 64) == "y" * 64


def test_ternary_as_event_argument(get_contract, get_logs):
    code = """
event Picked:
    xs: DynArray[Bytes[512], 5]

@external
def foo(c: bool, a: DynArray[Bytes[10], 5], b: DynArray[Bytes[512], 5]):
    log Picked(xs=a if c else b)
    """
    c = get_contract(code)

    c.foo(True, SHORT, LONG)
    (log,) = get_logs(c, "Picked")
    assert log.args.xs == SHORT

    c.foo(False, SHORT, LONG)
    (log,) = get_logs(c, "Picked")
    assert log.args.xs == LONG


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
    """
    c = get_contract(code)
    assert c.from_calls(True, b"abc", b"x" * 40) == (b"abc", 1)
    assert c.from_calls(False, b"abc", b"x" * 40) == (b"x" * 40, 2)
    assert c.from_locals(True, b"abc", b"x" * 40) == (b"abc", 1)
    assert c.from_locals(False, b"abc", b"x" * 40) == (b"x" * 40, 2)
