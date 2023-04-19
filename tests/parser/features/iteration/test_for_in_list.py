from decimal import Decimal

import pytest

from vyper.exceptions import (
    ArgumentException,
    ImmutableViolation,
    InvalidType,
    IteratorException,
    NamespaceCollision,
    StateAccessViolation,
    StructureException,
    TypeMismatch,
)

BASIC_FOR_LOOP_CODE = [
    # basic for-in-list memory
    (
        """
@external
def data() -> int128:
    s: int128[5] = [1, 2, 3, 4, 5]
    for i in s:
        if i >= 3:
            return i
    return -1""",
        3,
    ),
    # basic for-in-dynamic array
    (
        """
@external
def data() -> int128:
    s: DynArray[int128, 10] = [1, 2, 3, 4, 5]
    for i in s:
        if i >= 3:
            return i
    return -1""",
        3,
    ),
    # test more complicated type
    (
        """
struct S:
    x: int128
    y: int128

@external
def data() -> int128:
    sss: DynArray[DynArray[S, 10], 10] = [
        [S({x:1, y:2})],
        [S({x:3, y:4}), S({x:5, y:6}), S({x:7, y:8}), S({x:9, y:10})]
        ]
    ret: int128 = 0
    for ss in sss:
        for s in ss:
            ret += s.x + s.y
    return ret""",
        sum(range(1, 11)),
    ),
    # basic for-in-list literal
    (
        """
@external
def data() -> int128:
    for i in [3, 5, 7, 9]:
        if i > 5:
            return i
    return -1""",
        7,
    ),
    (
        # test variable string dynarray
        """
@external
def data() -> String[33]:
    xs: DynArray[String[33], 3] = ["hello", ",", "world"]
    for x in xs:
        if x == ",":
            return x
    return ""
    """,
        ",",
    ),
    (
        # test literal string dynarray
        """
@external
def data() -> String[33]:
    for x in ["hello", ",", "world"]:
        if x == ",":
            return x
    return ""
    """,
        ",",
    ),
    (
        # test nested string dynarray
        """
@external
def data() -> DynArray[String[33], 2]:
    for x in [["hello", "world"], ["goodbye", "world!"]]:
        if x[1] == "world":
            return x
    return []
    """,
        ["hello", "world"],
    ),
    # test nested array
    (
        """
@external
def data() -> int128:
    ret: int128 = 0
    xss: int128[3][3] = [[1,2,3],[4,5,6],[7,8,9]]
    for xs in xss:
        for x in xs:
            ret += x
    return ret""",
        sum(range(1, 10)),
    ),
    # test more complicated literal
    (
        """
struct S:
    x: int128
    y: int128

@external
def data() -> int128:
    ret: int128 = 0
    for ss in [[S({x:1, y:2})]]:
        for s in ss:
            ret += s.x + s.y
    return ret""",
        1 + 2,
    ),
    # basic for-in-list addresses
    (
        """
@external
def data() -> address:
    addresses: address[3] = [
        0x7d577a597B2742b498Cb5Cf0C26cDCD726d39E6e,
        0x82A978B3f5962A5b0957d9ee9eEf472EE55B42F1,
        0xDCEceAF3fc5C0a63d195d69b1A90011B7B19650D
    ]
    count: int128 = 0
    for i in addresses:
        count += 1
        if count == 2:
            return i
    return 0x0000000000000000000000000000000000000000
    """,
        "0x82A978B3f5962A5b0957d9ee9eEf472EE55B42F1",
    ),
]


@pytest.mark.parametrize("code, data", BASIC_FOR_LOOP_CODE)
def test_basic_for_in_lists(code, data, get_contract):
    c = get_contract(code)
    assert c.data() == data


def test_basic_for_list_storage(get_contract_with_gas_estimation):
    code = """
x: int128[4]

@external
def set():
    self.x = [3, 5, 7, 9]

@external
def data() -> int128:
    for i in self.x:
        if i > 5:
            return i
    return -1
    """

    c = get_contract_with_gas_estimation(code)

    assert c.data() == -1
    c.set(transact={})
    assert c.data() == 7


def test_basic_for_dyn_array_storage(get_contract_with_gas_estimation):
    code = """
x: DynArray[int128, 4]

@external
def set(xs: DynArray[int128, 4]):
    self.x = xs

@external
def data() -> int128:
    t: int128 = 0
    for i in self.x:
        t += i
    return t
    """

    c = get_contract_with_gas_estimation(code)

    assert c.data() == 0
    # test all sorts of lists
    for xs in [[3, 5, 7, 9], [4, 6, 8], [1, 2], [5], []]:
        c.set(xs, transact={})
        assert c.data() == sum(xs)


def test_basic_for_list_storage_address(get_contract_with_gas_estimation):
    code = """
addresses: address[3]

@external
def set(i: int128, val: address):
    self.addresses[i] = val

@external
def ret(i: int128) -> address:
    return self.addresses[i]

@external
def iterate_return_second() -> address:
    count: int128 = 0
    for i in self.addresses:
        count += 1
        if count == 2:
            return i
    return ZERO_ADDRESS
    """

    c = get_contract_with_gas_estimation(code)

    c.set(0, "0x82A978B3f5962A5b0957d9ee9eEf472EE55B42F1", transact={})
    c.set(1, "0x7d577a597B2742b498Cb5Cf0C26cDCD726d39E6e", transact={})
    c.set(2, "0xDCEceAF3fc5C0a63d195d69b1A90011B7B19650D", transact={})

    assert c.ret(1) == c.iterate_return_second() == "0x7d577a597B2742b498Cb5Cf0C26cDCD726d39E6e"


def test_basic_for_list_storage_decimal(get_contract_with_gas_estimation):
    code = """
readings: decimal[3]

@external
def set(i: int128, val: decimal):
    self.readings[i] = val

@external
def ret(i: int128) -> decimal:
    return self.readings[i]

@external
def i_return(break_count: int128) -> decimal:
    count: int128 = 0
    for i in self.readings:
        if count == break_count:
            return i
        count += 1
    return -1.111
    """

    c = get_contract_with_gas_estimation(code)

    c.set(0, Decimal("0.0001"), transact={})
    c.set(1, Decimal("1.1"), transact={})
    c.set(2, Decimal("2.2"), transact={})

    assert c.ret(2) == c.i_return(2) == Decimal("2.2")
    assert c.ret(1) == c.i_return(1) == Decimal("1.1")
    assert c.ret(0) == c.i_return(0) == Decimal("0.0001")


def test_for_in_list_iter_type(get_contract_with_gas_estimation):
    code = """
@external
@view
def func(amounts: uint256[3]) -> uint256:
    total: uint256 = as_wei_value(0, "wei")

    # calculate total
    for amount in amounts:
        total += amount

    return total
    """

    c = get_contract_with_gas_estimation(code)

    assert c.func([100, 200, 300]) == 600


def test_for_in_dyn_array(get_contract_with_gas_estimation):
    code = """
@external
@view
def func(amounts: DynArray[uint256, 3]) -> uint256:
    total: uint256 = 0

    # calculate total
    for amount in amounts:
        total += amount

    return total
    """

    c = get_contract_with_gas_estimation(code)

    assert c.func([100, 200, 300]) == 600
    assert c.func([100, 200]) == 300


GOOD_CODE = [
    # multiple for loops
    """
@external
def foo(x: int128):
    p: int128 = 0
    for i in range(3):
        p += i
    for i in range(4):
        p += i
    """,
    """
@external
def foo(x: int128):
    p: int128 = 0
    for i in range(3):
        p += i
    for i in [1, 2, 3, 4]:
        p += i
    """,
    """
@external
def foo(x: int128):
    p: int128 = 0
    for i in [1, 2, 3, 4]:
        p += i
    for i in [1, 2, 3, 4]:
        p += i
    """,
    """
@external
def foo():
    for i in range(10):
        pass
    for i in range(20):
        pass
    """,
    # using index variable after loop
    """
@external
def foo():
    for i in range(10):
        pass
    i: int128 = 100  # create new variable i
    i = 200  # look up the variable i and check whether it is in forvars
    """,
]


@pytest.mark.parametrize("code", GOOD_CODE)
def test_good_code(code, get_contract):
    get_contract(code)


RANGE_CONSTANT_CODE = [
    (
        """
TREE_FIDDY: constant(int128)  = 350


@external
def a() -> uint256:
    x: uint256 = 0
    for i in range(TREE_FIDDY):
        x += 1
    return x""",
        350,
    ),
    (
        """
ONE_HUNDRED: constant(int128)  = 100

@external
def a() -> uint256:
    x: uint256 = 0
    for i in range(1, 1 + ONE_HUNDRED):
        x += 1
    return x""",
        100,
    ),
    (
        """
START: constant(int128)  = 100
END: constant(int128)  = 199

@external
def a() -> uint256:
    x: uint256 = 0
    for i in range(START, END):
        x += 1
    return x""",
        99,
    ),
    (
        """
@external
def a() -> int128:
    x: int128 = 0
    for i in range(-5, -1):
        x += i
    return x""",
        -14,
    ),
]


@pytest.mark.parametrize("code, result", RANGE_CONSTANT_CODE)
def test_range_constant(get_contract, code, result):
    c = get_contract(code)

    assert c.a() == result


BAD_CODE = [
    # altering list within loop
    (
        """
@external
def data() -> int128:
    s: int128[6] = [1, 2, 3, 4, 5, 6]
    count: int128 = 0
    for i in s:
        s[count] = 1  # this should not be allowed.
        if i >= 3:
            return i
        count += 1
    return -1
    """,
        ImmutableViolation,
    ),
    (
        """
@external
def foo():
    s: int128[6] = [1, 2, 3, 4, 5, 6]
    count: int128 = 0
    for i in s:
        s[count] += 1
    """,
        ImmutableViolation,
    ),
    # alter storage list within for loop
    (
        """
s: int128[6]

@external
def set():
    self.s = [1, 2, 3, 4, 5, 6]

@external
def data() -> int128:
    count: int128 = 0
    for i in self.s:
        self.s[count] = 1  # this should not be allowed.
        if i >= 3:
            return i
        count += 1
    return -1
    """,
        ImmutableViolation,
    ),
    # alter nested storage list in internal function call within for loop
    (
        """
struct Foo:
    foo: uint256[4]

my_array2: Foo

@internal
def doStuff(i: uint256) -> uint256:
    self.my_array2.foo[i] = i
    return i

@internal
def _helper():
    i: uint256 = 0
    for item in self.my_array2.foo:
        self.doStuff(i)
        i += 1
    """,
        ImmutableViolation,
    ),
    # alter doubly nested storage list in internal function call within for loop
    (
        """
struct Foo:
    foo: uint256[4]

struct Bar:
    bar: Foo
    baz: uint256

my_array2: Bar

@internal
def doStuff(i: uint256) -> uint256:
    self.my_array2.bar.foo[i] = i
    return i

@internal
def _helper():
    i: uint256 = 0
    for item in self.my_array2.bar.foo:
        self.doStuff(i)
        i += 1
    """,
        ImmutableViolation,
    ),
    # alter entire struct with nested storage list in internal function call within for loop
    (
        """
struct Foo:
    foo: uint256[4]

my_array2: Foo

@internal
def doStuff():
    self.my_array2.foo = [
        block.timestamp + 1,
        block.timestamp + 2,
        block.timestamp + 3,
        block.timestamp + 4
    ]

@internal
def _helper():
    i: uint256 = 0
    for item in self.my_array2.foo:
        self.doStuff()
        i += 1
    """,
        ImmutableViolation,
    ),
    # invalid nested loop
    (
        """
@external
def foo(x: int128):
    for i in range(4):
        for i in range(5):
            pass
    """,
        NamespaceCollision,
    ),
    (
        """
@external
def foo(x: int128):
    for i in [1,2]:
        for i in [1,2]:
            pass
     """,
        NamespaceCollision,
    ),
    # invalid iterator assignment
    (
        """
@external
def foo(x: int128):
    for i in [1,2]:
        i = 2
    """,
        ImmutableViolation,
    ),
    # invalid modification of dynarray
    (
        """
@external
def foo():
    xs: DynArray[uint256, 5] = [1,2,3]
    for x in xs:
        xs.pop()
    """,
        ImmutableViolation,
    ),
    # invalid modification of dynarray
    (
        """
@external
def foo():
    xs: DynArray[uint256, 5] = [1,2,3]
    for x in xs:
        xs.append(x)
    """,
        ImmutableViolation,
    ),
    # invalid modification of dynarray
    (
        """
@external
def foo():
    xs: DynArray[DynArray[uint256, 5], 5] = [[1,2,3]]
    for x in xs:
        x.pop()
    """,
        ImmutableViolation,
    ),
    # invalid modification of dynarray
    (
        """
array: DynArray[uint256, 5]
@internal
def a():
    self.b()

@internal
def b():
    self.array.pop()

@external
def foo():
    for x in self.array:
        self.a()
    """,
        ImmutableViolation,
    ),
    (
        """
@external
def foo(x: int128):
    for i in [1,2]:
        i += 2
    """,
        ImmutableViolation,
    ),
    # range of < 1
    (
        """
@external
def foo():
    for i in range(-3):
        pass
    """,
        StructureException,
    ),
    """
@external
def foo():
    for i in range(0):
        pass
    """,
    """
@external
def foo():
    for i in []:
        pass
    """,
    """
FOO: constant(DynArray[uint256, 3]) = []

@external
def foo():
    for i in FOO:
        pass
    """,
    (
        """
@external
def foo():
    for i in range(5,3):
        pass
    """,
        StructureException,
    ),
    (
        """
@external
def foo():
    for i in range(5,3,-1):
        pass
    """,
        ArgumentException,
    ),
    (
        """
@external
def foo():
    a: uint256 = 2
    for i in range(a):
        pass
    """,
        StateAccessViolation,
    ),
    """
@external
def foo():
    a: int128 = 6
    for i in range(a,a-3):
        pass
    """,
    # invalid argument length
    (
        """
@external
def foo():
    for i in range():
        pass
    """,
        ArgumentException,
    ),
    (
        """
@external
def foo():
    for i in range(0,1,2):
        pass
    """,
        ArgumentException,
    ),
    # non-iterables
    (
        """
@external
def foo():
    for i in b"asdf":
        pass
    """,
        InvalidType,
    ),
    (
        """
@external
def foo():
    for i in 31337:
        pass
    """,
        InvalidType,
    ),
    (
        """
@external
def foo():
    for i in bar():
        pass
    """,
        IteratorException,
    ),
    (
        """
@external
def foo():
    for i in self.bar():
        pass
    """,
        IteratorException,
    ),
    (
        """
@external
def test_for() -> int128:
    a: int128 = 0
    for i in range(max_value(int128), max_value(int128)+2):
        a = i
    return a
    """,
        TypeMismatch,
    ),
    (
        """
@external
def test_for() -> int128:
    a: int128 = 0
    b: uint256 = 0
    for i in range(5):
        a = i
        b = i
    return a
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("code", BAD_CODE)
def test_bad_code(assert_compile_failed, get_contract, code):
    err = StructureException
    if not isinstance(code, str):
        code, err = code
    assert_compile_failed(lambda: get_contract(code), err)
