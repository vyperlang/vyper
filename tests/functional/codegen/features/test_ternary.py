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


@pytest.mark.parametrize("test", [True, False])
def test_ternary_dynarray_subscript(get_contract, test):
    code = """
@external
def foo(t: bool, a: DynArray[uint256, 3], b: DynArray[uint256, 3]) -> uint256:
    return (a if t else b)[0]
    """
    c = get_contract(code)

    a = [11, 22]
    b = [33, 44]
    assert c.foo(test, a, b) == (a if test else b)[0]


@pytest.mark.parametrize("test", [True, False])
def test_ternary_local_or_internal_param_subscript(get_contract, test):
    # inside `pick`, the ternary merges a pointer to the local `x` with the
    # pointer the caller passed for `y`; the read through it must not be
    # served from the earlier read of `x[0]`
    code = """
@internal
def pick(y: DynArray[uint256, 3], t: bool) -> uint256:
    x: DynArray[uint256, 3] = [1, 2]
    first_x: uint256 = x[0]
    return first_x + (x if t else y)[0]

@external
def foo(t: bool, y: DynArray[uint256, 3]) -> uint256:
    return self.pick(y, t)

@external
def bar(t: bool, y: DynArray[uint256, 3]) -> uint256:
    return self.pick(y, t) + 1
    """
    c = get_contract(code)

    y = [33, 44]
    expected = 1 + ([1, 2] if test else y)[0]
    assert c.foo(test, y) == expected
    assert c.bar(test, y) == expected + 1


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
    assert c.foo(test, x, y) == ((x, y) if test else (y, x))


@pytest.mark.parametrize("test", [True, False])
def test_ternary_immutable(get_contract, test):
    code = """
IMM: public(immutable(uint256))
@deploy
def __init__(test: bool):
    self.IMM = 1 if test else 2
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

    c.foo(test)
    assert c.foo_retval() == (5 if test else 7)

    if test:
        assert c.track_taint_x() == 1
        assert c.track_taint_y() == 0
    else:
        assert c.track_taint_x() == 0
        assert c.track_taint_y() == 1


def test_venom_ternary_with_memory_allocation(get_contract):
    source = """
buf: Bytes[10]

@external
def foo() -> Bytes[10]:
    x: bool = True
    self.buf = concat(b"\\x01", b"\\x02") if x else b""
    return self.buf
    """

    c = get_contract(source)
    assert c.foo() == b"\x01\x02"


@pytest.mark.parametrize("test", [True, False])
def test_ternary_as_internal_call_argument(get_contract, test):
    code = """
@internal
def _echo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    return xs

@external
def direct(c: bool, a: DynArray[uint256, 5], b: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    return self._echo(a if c else b)

@external
def via_local(
    c: bool, a: DynArray[uint256, 5], b: DynArray[uint256, 5]
) -> DynArray[uint256, 5]:
    xs: DynArray[uint256, 5] = a if c else b
    return self._echo(xs)
    """
    c = get_contract(code)
    a = [1, 2]
    b = [3, 4, 5]
    expected = a if test else b
    assert c.direct(test, a, b) == expected
    assert c.via_local(test, a, b) == expected


@pytest.mark.parametrize("test", [True, False])
def test_ternary_as_external_call_argument(get_contract, test):
    code = """
interface Echo:
    def echo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]: view

@external
def echo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    return xs

@external
def foo(c: bool, a: DynArray[uint256, 5], b: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    return staticcall Echo(self).echo(a if c else b)
    """
    c = get_contract(code)
    a = [1, 2]
    b = [3, 4, 5]
    assert c.foo(test, a, b) == (a if test else b)


def test_ternary_wildcard_arg_empty_arm(get_contract):
    target_code = """
@external
def sink(input: DynArray[Bytes[10], 3]) -> uint256:
    return len(input)
    """

    caller_code = """
interface Sink:
    def sink(input: DynArray[Bytes[10], ...]) -> uint256: nonpayable

@external
def do_it(addr: address, b: bool) -> uint256:
    return extcall Sink(addr).sink([] if b else [b"x"])
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.do_it(target.address, True) == 0
    assert caller.do_it(target.address, False) == 1


@pytest.mark.parametrize("test", [True, False])
def test_ternary_wildcard_arg_empty_smaller_capacity(get_contract, test):
    # the `empty()` element has a smaller capacity than the other arm's element
    target_code = """
@external
def echo(xs: DynArray[DynArray[uint256, 3], 3]) -> DynArray[DynArray[uint256, 3], 3]:
    return xs
    """

    caller_code = """
interface Target:
    def echo(
        xs: DynArray[DynArray[uint256, ...], 3]
    ) -> DynArray[DynArray[uint256, 3], 3]: nonpayable

@external
def foo(target: address, t: bool) -> DynArray[DynArray[uint256, 3], 3]:
    return extcall Target(target).echo([empty(DynArray[uint256, 2])] if t else [[1, 2, 3]])
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.foo(target.address, test) == ([[]] if test else [[1, 2, 3]])


@pytest.mark.parametrize("test", [True, False])
def test_ternary_as_event_argument(get_contract, get_logs, test):
    code = """
event Picked:
    xs: DynArray[uint256, 5]

@external
def foo(c: bool, a: DynArray[uint256, 5], b: DynArray[uint256, 5]):
    log Picked(xs=a if c else b)
    """
    c = get_contract(code)
    a = [1, 2]
    b = [3, 4, 5]
    c.foo(test, a, b)
    (log,) = get_logs(c, "Picked")
    assert log.args.xs == (a if test else b)


@pytest.mark.parametrize("test", [True, False])
def test_ternary_wildcard_arg_self_arm(get_contract, env, test):
    target_code = """
@external
def sink(input: DynArray[address, 3]) -> DynArray[address, 3]:
    return input
    """

    caller_code = """
interface Sink:
    def sink(input: DynArray[address, ...]) -> DynArray[address, 3]: nonpayable

@external
def do_it(addr: address, other: address, b: bool) -> DynArray[address, 3]:
    return extcall Sink(addr).sink([self] if b else [other])
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    other = env.accounts[1]
    expected = [caller.address if test else other]
    assert caller.do_it(target.address, other, test) == expected


@pytest.mark.parametrize("test", [True, False])
@pytest.mark.parametrize(
    "typ,arg,if_true,if_false",
    [
        (
            "DynArray[DynArray[uint256, 9], ...]",
            "[[1]] if b else [[2, 3], [4]]",
            [[1]],
            [[2, 3], [4]],
        ),
        (
            "DynArray[DynArray[uint256, 9], ...]",
            "[[2, 3], [4]] if b else [[1]]",
            [[2, 3], [4]],
            [[1]],
        ),
        ("DynArray[DynArray[uint256, 9], ...]", "[[1] if b else [2, 3]]", [[1]], [[2, 3]]),
        (
            "DynArray[DynArray[DynArray[uint256, 3], ...], ...]",
            "[[[1]]] if b else [[[2], [3, 4]]]",
            [[[1]]],
            [[[2], [3, 4]]],
        ),
        (
            "DynArray[DynArray[Bytes[9], 4], ...]",
            '[[b"ab"]] if b else [[b"cd", b"ef"]]',
            [[b"ab"]],
            [[b"cd", b"ef"]],
        ),
        (
            "DynArray[DynArray[uint256, 9][2], ...]",
            "[[[1], [2, 3]]] if b else [[[4], [5]], [[6], [7, 8]]]",
            [[[1], [2, 3]]],
            [[[4], [5]], [[6], [7, 8]]],
        ),
        (
            "(DynArray[DynArray[uint256, 9], ...], uint256)",
            "([[1]] if b else [[2, 3], [4]], 5)",
            ([[1]], 5),
            ([[2, 3], [4]], 5),
        ),
    ],
)
def test_ternary_wildcard_arg_nested_list(get_contract, typ, arg, if_true, if_false, test):
    # the literal fixes both the `...` lengths and the element type of the resolved type
    bounded_typ = typ.replace("...", "3")
    target_code = f"""
@external
def echo(xs: {bounded_typ}) -> {bounded_typ}:
    return xs
    """

    caller_code = f"""
interface Echo:
    def echo(xs: {typ}) -> {bounded_typ}: nonpayable

@external
def do_it(addr: address, b: bool) -> {bounded_typ}:
    return extcall Echo(addr).echo({arg})
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.do_it(target.address, test) == (if_true if test else if_false)


@pytest.mark.parametrize("test", [True, False])
@pytest.mark.parametrize(
    "typ,arg,if_true,if_false",
    [
        ("DynArray[DynArray[uint256, ...], 3]", "[[]] if b else [[1]]", [[]], [[1]]),
        (
            "DynArray[DynArray[uint256, ...], 3]",
            "[[], [1]] if b else [[2, 3], [4]]",
            [[], [1]],
            [[2, 3], [4]],
        ),
        (
            "DynArray[DynArray[DynArray[uint256, ...], ...], ...]",
            "[[[]]] if b else [[[1], [2, 3]]]",
            [[[]]],
            [[[1], [2, 3]]],
        ),
        (
            "DynArray[uint256, ...][2]",
            "[[], [1]] if b else [[1, 2], [3]]",
            [[], [1]],
            [[1, 2], [3]],
        ),
        ("DynArray[Bytes[100], ...]", '[b"x"] if b else []', [b"x"], []),
        ("DynArray[Bytes[100], ...]", '[] if b else [b"x"]', [], [b"x"]),
        ("DynArray[String[100], ...]", '["x"] if b else []', ["x"], []),
        (
            "(DynArray[DynArray[uint256, ...], 3], uint256)",
            "([[]] if b else [[1]], 7)",
            ([[]], 7),
            ([[1]], 7),
        ),
    ],
)
def test_ternary_wildcard_arg_empty_list(get_contract, typ, arg, if_true, if_false, test):
    # an empty list has no elements to take its type from, it is typed like
    # the ternary it is part of
    bounded_typ = typ.replace("...", "3")
    target_code = f"""
@external
def echo(xs: {bounded_typ}) -> {bounded_typ}:
    return xs
    """

    caller_code = f"""
interface Echo:
    def echo(xs: {typ}) -> {bounded_typ}: nonpayable

@external
def do_it(addr: address, b: bool) -> {bounded_typ}:
    return extcall Echo(addr).echo({arg})
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.do_it(target.address, test) == (if_true if test else if_false)


@pytest.mark.parametrize("test", [True, False])
def test_ternary_wildcard_arg_variables(get_contract, test):
    # the parameter's fixed inner bound is much larger than the variables', the
    # ternary is still typed (and allocated) with the variables' bounds
    target_code = """
@external
def echo(xs: DynArray[DynArray[uint256, 2], 2]) -> DynArray[DynArray[uint256, 2], 2]:
    return xs
    """

    caller_code = """
interface Echo:
    def echo(
        xs: DynArray[DynArray[uint256, 2**58], ...]
    ) -> DynArray[DynArray[uint256, 2], 2]: nonpayable

@external
def do_it(addr: address, b: bool) -> DynArray[DynArray[uint256, 2], 2]:
    xs: DynArray[DynArray[uint256, 2], 2] = [[1], [2, 3]]
    ys: DynArray[DynArray[uint256, 2], 2] = [[4, 5]]
    return extcall Echo(addr).echo(xs if b else ys)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.do_it(target.address, test) == ([[1], [2, 3]] if test else [[4, 5]])


@pytest.mark.parametrize("test", [True, False])
def test_ternary_as_for_loop_iterable(get_contract, test):
    # the loop allocates new buffers while it is still reading the selected
    # arm, so the buffer an arm was copied into must stay live for the
    # whole loop, whichever arm is taken
    code = """
a: DynArray[DynArray[uint256, 4], 3]
b: DynArray[DynArray[uint256, 4], 3]

@external
def set(a: DynArray[DynArray[uint256, 4], 3], b: DynArray[DynArray[uint256, 4], 3]):
    self.a = a
    self.b = b

@external
def from_storage(c: bool) -> DynArray[DynArray[uint256, 4], 3]:
    ys: DynArray[DynArray[uint256, 4], 3] = []
    for x: DynArray[uint256, 4] in (self.a if c else self.b):
        ys.append(x)
    return ys

@external
def storage_or_memory(
    c: bool, xs: DynArray[DynArray[uint256, 4], 3]
) -> DynArray[DynArray[uint256, 4], 3]:
    ys: DynArray[DynArray[uint256, 4], 3] = []
    for x: DynArray[uint256, 4] in (self.a if c else xs):
        ys.append(x)
    return ys

@external
def memory_or_storage(
    c: bool, xs: DynArray[DynArray[uint256, 4], 3]
) -> DynArray[DynArray[uint256, 4], 3]:
    ys: DynArray[DynArray[uint256, 4], 3] = []
    for x: DynArray[uint256, 4] in (xs if c else self.a):
        ys.append(x)
    return ys
    """
    a = [[1, 2], [], [3]]
    b = [[4, 5, 6, 7], [8]]
    xs = [[9], [10, 11, 12]]
    c = get_contract(code)
    c.set(a, b)
    assert c.from_storage(test) == (a if test else b)
    assert c.storage_or_memory(test, xs) == (a if test else xs)
    assert c.memory_or_storage(test, xs) == (xs if test else a)


@pytest.mark.parametrize("test", [True, False])
def test_ternary_wildcard_call_arm_as_for_loop_iterable(get_contract, test):
    # the loop variable does not pass its type on to the iterable, so the
    # first arm fixes the bounds of the call return in the other arm
    target_code = """
@external
@view
def bounded() -> DynArray[Bytes[10], 2]:
    return [b"ab", b"c"]

@external
@view
def wide() -> DynArray[Bytes[10], 2]:
    return [b"hello", b"vyper"]
    """

    caller_code = """
interface Target:
    def bounded() -> DynArray[Bytes[10], 2]: view
    def wide() -> DynArray[Bytes[...], ...]: view

@external
def do_it(addr: address, b: bool) -> DynArray[Bytes[10], 2]:
    ys: DynArray[Bytes[10], 2] = []
    for x: Bytes[10] in (
        staticcall Target(addr).bounded() if b else staticcall Target(addr).wide()
    ):
        ys.append(x)
    return ys
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    expected = [b"ab", b"c"] if test else [b"hello", b"vyper"]
    assert caller.do_it(target.address, test) == expected


@pytest.mark.parametrize("test", [True, False])
def test_ternary_tuple_assigned_to_storage(get_contract, test):
    # the selected tuple is copied into storage word by word through the
    # merged pointer; every member of either arm must reach storage
    code = """
x: (uint256, Bytes[64])
y: (uint256, Bytes[64])
target: (uint256, Bytes[64])

@external
def set(n: uint256, s: Bytes[64], m: uint256, t: Bytes[64]):
    u: (uint256, Bytes[64]) = (n, s)
    v: (uint256, Bytes[64]) = (m, t)
    self.x = u
    self.y = v

@external
def from_storage(c: bool):
    self.target = self.x if c else self.y

@external
def from_memory(c: bool, n: uint256, s: Bytes[64], m: uint256, t: Bytes[64]):
    u: (uint256, Bytes[64]) = (n, s)
    v: (uint256, Bytes[64]) = (m, t)
    self.target = u if c else v

@external
def get_target() -> (uint256, Bytes[64]):
    return self.target
    """
    x = (7, b"0123456789")
    y = (3, b"q" * 64)
    c = get_contract(code)
    c.set(*x, *y)

    c.from_storage(test)
    assert c.get_target() == (x if test else y)

    c.from_memory(test, *y, *x)
    assert c.get_target() == (y if test else x)


# GH issue 5199: `[]` and `empty(...)` arms have no location and used to
# panic in make_setter
empty_arm_cases = [
    ("DynArray[uint256, 2]", "[]", "[]", [], []),
    ("DynArray[uint256, 2]", "[]", "[1]", [], [1]),
    ("DynArray[uint256, 2]", "[1, 2]", "[]", [1, 2], []),
    ("DynArray[uint256, 2]", "empty(DynArray[uint256, 2])", "empty(DynArray[uint256, 2])", [], []),
    ("DynArray[uint256, 2]", "empty(DynArray[uint256, 2])", "[3]", [], [3]),
    ("uint256[2]", "empty(uint256[2])", "[1, 2]", [0, 0], [1, 2]),
    ("uint256[2]", "empty(uint256[2])", "empty(uint256[2])", [0, 0], [0, 0]),
    ("Bytes[10]", "empty(Bytes[10])", "empty(Bytes[10])", b"", b""),
    ("Bytes[10]", "b'ab'", "empty(Bytes[10])", b"ab", b""),
    ("String[10]", "empty(String[10])", '"ab"', "", "ab"),
]


@pytest.mark.parametrize("typ,body,orelse,body_value,orelse_value", empty_arm_cases)
@pytest.mark.parametrize("test", [True, False])
def test_ternary_empty_arm(get_contract, typ, body, orelse, body_value, orelse_value, test):
    code = f"""
@external
def foo(t: bool) -> {typ}:
    tmp: {typ} = {body} if t else {orelse}
    return tmp

@external
def bar(t: bool) -> {typ}:
    return {body} if t else {orelse}
    """
    c = get_contract(code)
    expected = body_value if test else orelse_value
    assert c.foo(test) == expected
    assert c.bar(test) == expected


@pytest.mark.parametrize("test", [True, False])
def test_ternary_empty_struct_arm(get_contract, test):
    code = """
struct S:
    a: uint256
    b: DynArray[uint256, 3]

@external
def foo(t: bool) -> S:
    x: S = empty(S) if t else S(a=1, b=[2, 3])
    return x

@external
def bar(t: bool) -> S:
    return S(a=1, b=[2, 3]) if t else empty(S)

@external
def baz(t: bool) -> S:
    return empty(S) if t else empty(S)
    """
    c = get_contract(code)
    empty_s = (0, [])
    s = (1, [2, 3])
    assert c.foo(test) == (empty_s if test else s)
    assert c.bar(test) == (s if test else empty_s)
    assert c.baz(test) == empty_s
