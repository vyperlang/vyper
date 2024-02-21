import pytest

simple_cases = [
    (
        """
@external
def foo(t: bool, x: uint256, y: uint256) -> uint256:
    return x if t else y
    """,
        (1, 2),
    ),
    (  # literal test
        """
@external
def foo(_t: bool, x: uint256, y: uint256) -> uint256:
    return x if {test} else y
    """,
        (1, 2),
    ),
    (  # literal body
        """
@external
def foo(t: bool, _x: uint256, y: uint256) -> uint256:
    return {x} if t else y
    """,
        (1, 2),
    ),
    (  # literal orelse
        """
@external
def foo(t: bool, x: uint256, _y: uint256) -> uint256:
    return x if t else {y}
    """,
        (1, 2),
    ),
    (  # literal body/orelse
        """
@external
def foo(t: bool, _x: uint256, _y: uint256) -> uint256:
    return {x} if t else {y}
    """,
        (1, 2),
    ),
    (  # literal everything
        """
@external
def foo(_t: bool, _x: uint256, _y: uint256) -> uint256:
    return {x} if {test} else {y}
    """,
        (1, 2),
    ),
    (  # body/orelse in storage and memory
        """
s: uint256
@external
def foo(t: bool, x: uint256, y: uint256) -> uint256:
    self.s = x
    return self.s if t else y
    """,
        (1, 2),
    ),
    (  # body/orelse in memory and storage
        """
s: uint256
@external
def foo(t: bool, x: uint256, y: uint256) -> uint256:
    self.s = x
    return self.s if t else y
    """,
        (1, 2),
    ),
    (  # body/orelse in memory and constant
        """
S: constant(uint256) = {y}
@external
def foo(t: bool, x: uint256, _y: uint256) -> uint256:
    return x if t else S
    """,
        (1, 2),
    ),
    (  # dynarray
        """
@external
def foo(t: bool, x: DynArray[uint256, 3], y: DynArray[uint256, 3]) -> DynArray[uint256, 3]:
    return x if t else y
    """,
        ([], [1]),
    ),
    (  # variable + literal dynarray
        """
@external
def foo(t: bool, x: DynArray[uint256, 3], _y: DynArray[uint256, 3]) -> DynArray[uint256, 3]:
    return x if t else {y}
    """,
        ([], [1]),
    ),
    (  # literal + variable dynarray
        """
@external
def foo(t: bool, _x: DynArray[uint256, 3], y: DynArray[uint256, 3]) -> DynArray[uint256, 3]:
    return {x} if t else y
    """,
        ([], [1]),
    ),
    (  # storage dynarray
        """
s: DynArray[uint256, 3]
@external
def foo(t: bool, x: DynArray[uint256, 3], y: DynArray[uint256, 3]) -> DynArray[uint256, 3]:
    self.s = y
    return x if t else self.s
    """,
        ([], [1]),
    ),
    (  # static array
        """
@external
def foo(t: bool, x: uint256[1], y: uint256[1]) -> uint256[1]:
    return x if t else y
    """,
        ([2], [1]),
    ),
    (  # static array literal
        """
@external
def foo(t: bool, x: uint256[1], _y: uint256[1]) -> uint256[1]:
    return x if t else {y}
    """,
        ([2], [1]),
    ),
    (  # strings
        """
@external
def foo(t: bool, x: String[10], y: String[10]) -> String[10]:
    return x if t else y
    """,
        ("hello", "world"),
    ),
    (  # string literal
        """
@external
def foo(t: bool, x: String[10], _y: String[10]) -> String[10]:
    return x if t else {y}
    """,
        ("hello", "world"),
    ),
    (  # bytes
        """
@external
def foo(t: bool, x: Bytes[10], y: Bytes[10]) -> Bytes[10]:
    return x if t else y
    """,
        (b"hello", b"world"),
    ),
]


@pytest.mark.parametrize("code,inputs", simple_cases)
@pytest.mark.parametrize("test", [True, False])
def test_ternary_simple(get_contract, code, test, inputs):
    x, y = inputs
    # note: repr to escape strings
    code = code.format(test=test, x=repr(x), y=repr(y))
    c = get_contract(code)
    # careful with order of precedence of `assert` and `if/else` in python!
    assert c.foo(test, x, y) == (x if test else y)


tuple_codes = [
    """
@external
def foo(t: bool, x: uint256, y: uint256) -> (uint256, uint256):
    return (x, y) if t else (y, x)
    """,
    """
s: uint256
@external
def foo(t: bool, x: uint256, y: uint256) -> (uint256, uint256):
    self.s = x
    return (self.s, y) if t else (y, self.s)
    """,
]


@pytest.mark.parametrize("code", tuple_codes)
@pytest.mark.parametrize("test", [True, False])
def test_ternary_tuple(get_contract, code, test):
    c = get_contract(code)

    x, y = 1, 2
    assert c.foo(test, x, y) == ([x, y] if test else [y, x])


@pytest.mark.parametrize("test", [True, False])
def test_ternary_immutable(get_contract, test):
    code = """
IMM: public(immutable(uint256))
@deploy
def __init__(test: bool):
    IMM = 1 if test else 2
    """
    c = get_contract(code, test)

    assert c.IMM() == (1 if test else 2)


@pytest.mark.parametrize("test", [True, False])
@pytest.mark.parametrize("x", list(range(8)))
@pytest.mark.parametrize("y", list(range(8)))
def test_complex_ternary_expression(get_contract, test, x, y):
    code = """
@external
def foo(t: bool, x: uint256, y: uint256) -> uint256:
    return (x * y) if (t and True) else (x + y + convert(t, uint256))
    """
    c = get_contract(code)

    assert c.foo(test, x, y) == ((x * y) if (test and True) else (x + y + int(test)))


@pytest.mark.parametrize("test", [True, False])
@pytest.mark.parametrize("x", list(range(8)))
@pytest.mark.parametrize("y", list(range(8)))
def test_ternary_precedence(get_contract, test, x, y):
    code = """
@external
def foo(t: bool, x: uint256, y: uint256) -> uint256:
    return x * y if t else x + y + convert(t, uint256)
    """
    c = get_contract(code)

    assert c.foo(test, x, y) == (x * y if test else x + y + int(test))


@pytest.mark.parametrize("test1", [True, False])
@pytest.mark.parametrize("test2", [True, False])
def test_nested_ternary(get_contract, test1, test2):
    code = """
@external
def foo(t1: bool, t2: bool, x: uint256, y: uint256, z: uint256) -> uint256:
    return x if t1 else y if t2 else z
    """
    c = get_contract(code)

    x, y, z = 1, 2, 3
    assert c.foo(test1, test2, x, y, z) == (x if test1 else y if test2 else z)


@pytest.mark.parametrize("test", [True, False])
def test_ternary_side_effects(get_contract, test):
    code = """
track_taint_x: public(uint256)
track_taint_y: public(uint256)
foo_retval: public(uint256)

@internal
def x() -> uint256:
    self.track_taint_x += 1
    return 5

@internal
def y() -> uint256:
    self.track_taint_y += 1
    return 7

@external
def foo(t: bool):
    self.foo_retval = self.x() if t else self.y()
    """
    c = get_contract(code)

    c.foo(test, transact={})
    assert c.foo_retval() == (5 if test else 7)

    if test:
        assert c.track_taint_x() == 1
        assert c.track_taint_y() == 0
    else:
        assert c.track_taint_x() == 0
        assert c.track_taint_y() == 1
