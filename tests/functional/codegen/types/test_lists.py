import itertools

import pytest

from vyper.exceptions import ArrayIndexException, OverflowException, TypeMismatch


def test_list_tester_code(get_contract_with_gas_estimation):
    list_tester_code = """
z: int128[3]
z2: int128[2][2]
z3: int128[2]

@external
def foo(x: int128[3]) -> int128:
    return x[0] + x[1] + x[2]

@external
def goo(x: int128[2][2]) -> int128:
    return x[0][0] + x[0][1] + x[1][0] * 10 + x[1][1] * 10

@external
def hoo(x: int128[3]) -> int128:
    y: int128[3] = x
    return y[0] + x[1] + y[2]

@external
def joo(x: int128[2][2]) -> int128:
    y: int128[2][2] = x
    y2: int128[2] = x[1]
    return y[0][0] + y[0][1] + y2[0] * 10 + y2[1] * 10

@external
def koo(x: int128[3]) -> int128:
    self.z = x
    return self.z[0] + x[1] + self.z[2]

@external
def loo(x: int128[2][2]) -> int128:
    self.z2 = x
    self.z3 = x[1]
    return self.z2[0][0] + self.z2[0][1] + self.z3[0] * 10 + self.z3[1] * 10
    """

    c = get_contract_with_gas_estimation(list_tester_code)
    assert c.foo([3, 4, 5]) == 12
    assert c.goo([[1, 2], [3, 4]]) == 73
    assert c.hoo([3, 4, 5]) == 12
    assert c.joo([[1, 2], [3, 4]]) == 73
    assert c.koo([3, 4, 5]) == 12
    assert c.loo([[1, 2], [3, 4]]) == 73
    print("Passed list tests")


def test_list_output_tester_code(get_contract_with_gas_estimation):
    list_output_tester_code = """
z: int128[2]

@external
def foo() -> int128[2]:
    return [3, 5]

@external
def goo() -> int128[2]:
    x: int128[2] = [3, 5]
    return x

@external
def hoo() -> int128[2]:
    self.z = [3, 5]
    return self.z

@external
def joo() -> int128[2]:
    self.z = [3, 5]
    x: int128[2] = self.z
    return x

@external
def koo() -> int128[2][2]:
    return [[1, 2], [3, 4]]

@external
def loo() -> int128[2][2]:
    x: int128[2][2] = [[1, 2], [3, 4]]
    return x

@external
def moo() -> int128[2][2]:
    x: int128[2] = [1,2]
    return [x, [3,4]]

@external
def noo(inp: int128[2]) -> int128[2]:
    return inp

@external
def poo(inp: int128[2][2]) -> int128[2][2]:
    return inp

@external
def qoo(inp: int128[2]) -> int128[2][2]:
    return [inp, [3,4]]

@external
def roo(inp: decimal[2]) -> decimal[2][2]:
    return [inp, [3.0, 4.0]]
    """

    c = get_contract_with_gas_estimation(list_output_tester_code)
    assert c.foo() == [3, 5]
    assert c.goo() == [3, 5]
    assert c.hoo() == [3, 5]
    assert c.joo() == [3, 5]
    assert c.koo() == [[1, 2], [3, 4]]
    assert c.loo() == [[1, 2], [3, 4]]
    assert c.moo() == [[1, 2], [3, 4]]
    assert c.noo([3, 5]) == [3, 5]
    assert c.poo([[1, 2], [3, 4]]) == [[1, 2], [3, 4]]
    assert c.qoo([1, 2]) == [[1, 2], [3, 4]]
    assert c.roo([1, 2]) == [[1.0, 2.0], [3.0, 4.0]]

    print("Passed list output tests")


def test_array_accessor(get_contract_with_gas_estimation):
    array_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: int128[4] = [0, 0, 0, 0]
    a[0] = x
    a[1] = y
    a[2] = z
    a[3] = w
    return a[0] * 1000 + a[1] * 100 + a[2] * 10 + a[3]
    """

    c = get_contract_with_gas_estimation(array_accessor)
    assert c.test_array(2, 7, 1, 8) == 2718
    print("Passed basic array accessor test")


def test_two_d_array_accessor(get_contract_with_gas_estimation):
    two_d_array_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: int128[2][2] = [[0, 0], [0, 0]]
    a[0][0] = x
    a[0][1] = y
    a[1][0] = z
    a[1][1] = w
    return a[0][0] * 1000 + a[0][1] * 100 + a[1][0] * 10 + a[1][1]
    """

    c = get_contract_with_gas_estimation(two_d_array_accessor)
    assert c.test_array(2, 7, 1, 8) == 2718
    print("Passed complex array accessor test")


def test_three_d_array_accessor(get_contract_with_gas_estimation):
    three_d_array_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: int128[2][2][2] = [[[0, 0], [0, 0]], [[0, 0], [0, 0]]]
    a[0][0][0] = x
    a[0][0][1] = y
    a[0][1][0] = z
    a[0][1][1] = w
    a[1][0][0] = -x
    a[1][0][1] = -y
    a[1][1][0] = -z
    a[1][1][1] = -w
    return a[0][0][0] * 1000 + a[0][0][1] * 100 + a[0][1][0] * 10 + a[0][1][1] + \\
        a[1][1][1] * 1000 + a[1][1][0] * 100 + a[1][0][1] * 10 + a[1][0][0]
    """

    c = get_contract_with_gas_estimation(three_d_array_accessor)
    assert c.test_array(2, 7, 1, 8) == -5454


def test_four_d_array_accessor(get_contract_with_gas_estimation):
    four_d_array_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: int128[2][2][2][2] = \\
        [[[[0, 0], [0, 0]], [[0, 0], [0, 0]]], [[[0, 0], [0, 0]], [[0, 0], [0, 0]]]]
    a[0][0][0][0] = x
    a[0][0][0][1] = y
    a[0][0][1][0] = z
    a[0][0][1][1] = w
    a[0][1][0][0] = -x
    a[0][1][0][1] = -y
    a[0][1][1][0] = -z
    a[0][1][1][1] = -w

    a[1][0][0][0] = x + 1
    a[1][0][0][1] = y + 1
    a[1][0][1][0] = z + 1
    a[1][0][1][1] = w + 1
    a[1][1][0][0] = - (x + 1)
    a[1][1][0][1] = - (y + 1)
    a[1][1][1][0] = - (z + 1)
    a[1][1][1][1] = - (w + 1)
    return a[0][0][0][0] * 1000 + a[0][0][0][1] * 100 + a[0][0][1][0] * 10 + a[0][0][1][1] + \\
        a[0][1][1][1] * 1000 + a[0][1][1][0] * 100 + a[0][1][0][1] * 10 + a[0][1][0][0] + \\
        a[1][0][0][0] * 1000 + a[1][0][0][1] * 100 + a[1][0][1][0] * 10 + a[1][0][1][1] + \\
        a[1][1][1][1] * 1000 + a[1][1][1][0] * 100 + a[1][1][0][1] * 10 + a[1][1][0][0]
    """

    c = get_contract_with_gas_estimation(four_d_array_accessor)
    assert c.test_array(2, 7, 1, 8) == -10908


def test_array_negative_accessor(get_contract_with_gas_estimation, assert_compile_failed):
    array_negative_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: int128[4] = [0, 0, 0, 0]
    a[0] = x
    a[1] = y
    a[2] = z
    a[3] = w
    return a[-4] * 1000 + a[-3] * 100 + a[-2] * 10 + a[-1]
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(array_negative_accessor), ArrayIndexException
    )

    two_d_array_negative_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: int128[2][2] = [[0, 0], [0, 0]]
    a[0][0] = x
    a[0][1] = y
    a[1][0] = z
    a[1][1] = w
    return a[-2][-2] * 1000 + a[-2][-1] * 100 + a[-1][-2] * 10 + a[-1][-1]
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(two_d_array_negative_accessor), ArrayIndexException
    )

    three_d_array_negative_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: int128[2][2][2] = [[[0, 0], [0, 0]], [[0, 0], [0, 0]]]
    a[0][0][0] = x
    a[0][0][1] = y
    a[0][1][0] = z
    a[0][1][1] = w
    a[1][0][0] = -x
    a[1][0][1] = -y
    a[1][1][0] = -z
    a[1][1][1] = -w
    return a[-2][-2][-2] * 1000 + a[-2][-2][-1] * 100 + a[-2][-1][-2] * 10 + a[-2][-1][-1] + \\
        a[-1][-1][-1] * 1000 + a[-1][-1][-2] * 100 + a[-1][-2][-1] * 10 + a[-1][-2][-2]
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(three_d_array_negative_accessor),
        ArrayIndexException,
    )

    four_d_array_negative_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: int128[2][2][2][2] = \\
        [[[[0, 0], [0, 0]], [[0, 0], [0, 0]]], [[[0, 0], [0, 0]], [[0, 0], [0, 0]]]]
    a[0][0][0][0] = x
    a[0][0][0][1] = y
    a[0][0][1][0] = z
    a[0][0][1][1] = w
    a[0][1][0][0] = -x
    a[0][1][0][1] = -y
    a[0][1][1][0] = -z
    a[0][1][1][1] = -w

    a[1][0][0][0] = x + 1
    a[1][0][0][1] = y + 1
    a[1][0][1][0] = z + 1
    a[1][0][1][1] = w + 1
    a[1][1][0][0] = - (x + 1)
    a[1][1][0][1] = - (y + 1)
    a[1][1][1][0] = - (z + 1)
    a[1][1][1][1] = - (w + 1)
    return a[-2][-2][-2][-2] * 1000 + a[-2][-2][-2][-1] * 100 + \\
        a[-2][-2][-1][-2] * 10 + a[-2][-2][-1][-1] + \\
        a[-2][-1][-1][-1] * 1000 + a[-2][-1][-1][-2] * 100 + \\
        a[-2][-1][-2][-1] * 10 + a[-2][-1][-2][-2] + \\
        a[-1][-2][-2][-2] * 1000 + a[-1][-2][-2][-1] * 100 + \\
        a[-1][-2][-1][-2] * 10 + a[-1][-2][-1][-1] + \\
        a[-1][-1][-1][-1] * 1000 + a[-1][-1][-1][-2] * 100 + \\
        a[-1][-1][-2][-1] * 10 + a[-1][-1][-2][-2]
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(four_d_array_negative_accessor),
        ArrayIndexException,
    )


def test_returns_lists(get_contract_with_gas_estimation):
    code = """
@external
def test_array_num_return() -> int128[2][2]:
    a: int128[2][2] = [[1, 2], [3, 4]]
    return a

@external
def test_array_decimal_return1() -> decimal[2][2]:
    a: decimal[2][2] = [[1.0, 2.0], [3.0, 4.0]]
    return a

@external
def test_array_decimal_return2() -> decimal[2][2]:
    return [[1.0, 2.0], [3.0, 4.0]]

@external
def test_array_decimal_return3() -> decimal[2][2]:
    a: decimal[2][2] = [[1.0, 2.0], [3.0, 4.0]]
    return a
"""

    c = get_contract_with_gas_estimation(code)
    assert c.test_array_num_return() == [[1, 2], [3, 4]]
    assert c.test_array_decimal_return1() == [[1.0, 2.0], [3.0, 4.0]]
    assert c.test_array_decimal_return2() == [[1.0, 2.0], [3.0, 4.0]]
    assert c.test_array_decimal_return3() == [[1.0, 2.0], [3.0, 4.0]]


def test_mult_list(get_contract_with_gas_estimation):
    code = """
@external
def test_multi3() -> uint256[2][2][2]:
    l: uint256[2][2][2] = [[[0, 0], [0, 4]], [[0, 0], [0, 123]]]
    return l

@external
def test_multi4() -> uint256[2][2][2][2]:
    l: uint256[2][2][2][2] = [[[[1, 0], [0, 4]], [[0, 0], [0, 0]]], [[[444, 0], [0, 0]],[[1, 0], [0, 222]]]]  # noqa: E501
    return l
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test_multi3() == [[[0, 0], [0, 4]], [[0, 0], [0, 123]]]
    assert c.test_multi4() == [
        [[[1, 0], [0, 4]], [[0, 0], [0, 0]]],
        [[[444, 0], [0, 0]], [[1, 0], [0, 222]]],
    ]


@pytest.mark.parametrize("type_", ["uint8", "uint256"])
def test_unsigned_accessors(get_contract_with_gas_estimation, tx_failed, type_):
    code = f"""
@external
def bounds_check(ix: {type_}) -> uint256:
    xs: uint256[3] = [1,2,3]
    return xs[ix]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bounds_check(0) == 1
    assert c.bounds_check(2) == 3
    with tx_failed():
        c.bounds_check(3)


@pytest.mark.parametrize("type_", ["int128", "int256"])
def test_signed_accessors(get_contract_with_gas_estimation, tx_failed, type_):
    code = f"""
@external
def bounds_check(ix: {type_}) -> uint256:
    xs: uint256[3] = [1,2,3]
    return xs[ix]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bounds_check(0) == 1
    assert c.bounds_check(2) == 3
    with tx_failed():
        c.bounds_check(3)
    with tx_failed():
        c.bounds_check(-1)


def test_list_check_heterogeneous_types(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@external
def fail() -> uint256:
    xs: uint256[3] = [1,2,3]
    return xs[3]
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ArrayIndexException)
    code = """
@external
def fail() -> uint256:
    xs: uint256[3] = [1,2,3]
    return xs[-1]
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ArrayIndexException)


def test_compile_time_bounds_check(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@external
def parse_list_fail():
    xs: uint256[3] = [2**256, 1, 3]
    pass
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), OverflowException)


def test_2d_array_input_1(get_contract):
    code = """
@internal
def test_input(arr: int128[2][1], i: int128) -> (int128[2][1], int128):
    return arr, i

@external
def test_values(arr: int128[2][1], i: int128) -> (int128[2][1], int128):
    return self.test_input(arr, i)
    """

    c = get_contract(code)
    assert c.test_values([[1, 2]], 3) == [[[1, 2]], 3]


def test_2d_array_input_2(get_contract):
    code = """
@internal
def test_input(arr: int128[2][3], s: String[10]) -> (int128[2][3], String[10]):
    return arr, s

@external
def test_values(arr: int128[2][3], s: String[10]) -> (int128[2][3], String[10]):
    return self.test_input(arr, s)
    """

    c = get_contract(code)
    assert c.test_values([[1, 2], [3, 4], [5, 6]], "abcdef") == [[[1, 2], [3, 4], [5, 6]], "abcdef"]


def test_nested_index_of_returned_array(get_contract):
    code = """
@internal
def inner() -> (int128, int128):
    return 1,2

@external
def outer() -> int128[2]:
    return [333, self.inner()[0]]
    """

    c = get_contract(code)
    assert c.outer() == [333, 1]


def test_nested_calls_inside_arrays(get_contract):
    code = """
@internal
def _foo(a: uint256, b: uint256[2]) -> (uint256, uint256, uint256, uint256, uint256):
    return 1, a, b[0], b[1], 5

@internal
def _foo2() -> uint256:
    a: uint256[10] = [6,7,8,9,10,11,12,13,15,16]
    return 4

@external
def foo() -> (uint256, uint256, uint256, uint256, uint256):
    return self._foo(2, [3, self._foo2()])
    """

    c = get_contract(code)
    assert c.foo() == [1, 2, 3, 4, 5]


def test_nested_calls_inside_arrays_with_index_access(get_contract):
    code = """
@internal
def _foo(a: uint256[2], b: uint256[2]) -> (uint256, uint256, uint256, uint256, uint256):
    return a[1]-b[0], 2, a[0]-b[1], 8-b[1], 5

@internal
def _foo2() -> (uint256, uint256):
    a: uint256[10] = [6,7,8,9,10,11,12,13,15,16]
    return a[6], 4

@external
def foo() -> (uint256, uint256, uint256, uint256, uint256):
    return self._foo([7, self._foo2()[0]], [11, self._foo2()[1]])
    """

    c = get_contract(code)
    assert c.foo() == [1, 2, 3, 4, 5]


def test_so_many_things_you_should_never_do(get_contract):
    code = """
@internal
def _foo(a: uint256[2], b: uint256[2]) -> uint256[5]:
    return [a[1]-b[0], 2, a[0]-b[1], 8-b[1], 5]

@internal
def _foo2() -> (uint256, uint256):
    b: uint256[2] = [5, 8]
    a: uint256[10] = [6,7,8,9,10,11,12,13,self._foo([44,b[0]],b)[4],16]
    return a[6], 4

@external
def foo() -> (uint256, uint256[3], uint256[2]):
    x: uint256[3] = [1, 14-self._foo2()[0], self._foo([7,self._foo2()[0]], [11,self._foo2()[1]])[2]]
    return 666, x, [88, self._foo2()[0]]
    """
    c = get_contract(code)
    assert c.foo() == [666, [1, 2, 3], [88, 12]]


def test_list_of_dynarray(get_contract):
    code = """
@external
def bar(x: int128) -> DynArray[int128, 2][2]:
    a: DynArray[int128, 2][2] = [[x, x * 2], [x * 3, x * 4]]
    return a

@external
def foo(x: int128) -> int128:
    a: DynArray[int128, 2][2] = [[x, x * 2], [x * 3, x * 4]]
    return a[0][0] * a[1][1]
    """
    c = get_contract(code)
    assert c.bar(7) == [[7, 14], [21, 28]]
    assert c.foo(7) == 196


def test_list_of_nested_dynarray(get_contract):
    code = """
@external
def bar(x: int128) -> DynArray[int128, 2][2][2]:
    a: DynArray[int128, 2][2][2] = [
        [[x, x * 2], [x * 3, x * 4]],
        [[x * 5, x * 6], [x * 7, x * 8]],
    ]
    return a

@external
def foo(x: int128) -> int128:
    a: DynArray[int128, 2][2][2] = [
        [[x, x * 2], [x * 3, x * 4]],
        [[x * 5, x * 6], [x * 7, x * 8]],
    ]
    return a[0][0][0] * a[1][1][1]
    """
    c = get_contract(code)
    assert c.bar(7) == [[[7, 14], [21, 28]], [[35, 42], [49, 56]]]
    assert c.foo(7) == 392


def test_list_of_structs_arg(get_contract):
    code = """
struct Foo:
    x: uint256
    y: uint256

@external
def bar(_baz: Foo[3]) -> uint256:
    sum: uint256 = 0
    for i: uint256 in range(3):
        sum += _baz[i].x * _baz[i].y
    return sum
    """
    c = get_contract(code)
    c_input = [[x, y] for x, y in zip(range(3), range(3))]
    assert c.bar(c_input) == 5  # 0 * 0 + 1 * 1 + 2 * 2


def test_list_of_structs_arg_with_dynamic_type(get_contract):
    code = """
struct Foo:
    x: uint256
    _msg: String[32]

@external
def bar(_baz: Foo[3]) -> String[96]:
    return concat(_baz[0]._msg, _baz[1]._msg, _baz[2]._msg)
    """
    c = get_contract(code)
    c_input = [[i, msg] for i, msg in enumerate(("Hello ", "world", "!!!!"))]
    assert c.bar(c_input) == "Hello world!!!!"


def test_list_of_nested_struct_arrays(get_contract):
    code = """
struct Ded:
    a: uint256[3]
    b: bool

struct Foo:
    c: uint256
    d: uint256
    e: Ded

struct Bar:
    f: Foo[3]
    g: DynArray[uint256, 3]

@external
def bar(_bar: Bar[3]) -> uint256:
    sum: uint256 = 0
    for i: uint256 in range(3):
        sum += _bar[i].f[0].e.a[0] * _bar[i].f[1].e.a[1]
    return sum
    """
    c = get_contract(code)
    c_input = [
        ((tuple([(123, 456, ([i, i + 1, i + 2], False))] * 3)), [9, 8, 7]) for i in range(1, 4)
    ]

    assert c.bar(c_input) == 20


def test_2d_list_of_struct(get_contract):
    code = """
struct Bar:
    a: uint256
    b: uint256

@external
def foo(x: Bar[2][2]) -> uint256:
    return x[0][0].a + x[1][1].b
    """
    c = get_contract(code)
    c_input = [([i, i * 2], [i * 3, i * 4]) for i in range(1, 3)]
    assert c.foo(c_input) == 9


def test_3d_list_of_struct(get_contract):
    code = """
struct Bar:
    a: uint256
    b: uint256

@external
def foo(x: Bar[2][2][2]) -> uint256:
    return x[0][0][0].a + x[1][1][1].b
    """
    c = get_contract(code)
    c_input = [([([i, i * 2], [i * 3, i * 4]) for i in range(1, 3)])] * 2
    assert c.foo(c_input) == 9


@pytest.mark.parametrize(
    "type,value",
    [
        ("decimal", [5.0, 11.0, 17.0, 29.0, 37.0, 41.0]),
        ("uint8", [0, 1, 17, 250, 255, 2]),
        ("int128", [0, -1, 1, -(2**127), 2**127 - 1, -50]),
        ("int256", [0, -1, 1, -(2**255), 2**255 - 1, -50]),
        ("uint256", [0, 1, 2**8, 2**255 + 1, 2**256 - 1, 100]),
        (
            "uint256",
            [2**255 + 1, 2**255 + 2, 2**255 + 3, 2**255 + 4, 2**255 + 5, 2**255 + 6],
        ),
        ("bool", [True, False, True, False, True, False]),
    ],
)
def test_constant_list(get_contract, tx_failed, type, value):
    code = f"""
MY_LIST: constant({type}[{len(value)}]) = {value}
@external
def ix(i: uint256) -> {type}:
    return MY_LIST[i]
    """
    c = get_contract(code)
    for i, p in enumerate(value):
        assert c.ix(i) == p
    # assert oob
    with tx_failed():
        c.ix(len(value) + 1)


def test_nested_constant_list_accessor(get_contract):
    code = """
@external
def foo() -> bool:
    f: uint256 = 1
    a: bool = 1 == [1,2,4][f] + -1
    return a
    """
    c = get_contract(code)
    assert c.foo() is True


# Would be nice to put this somewhere accessible, like in vyper.types or something
integer_types = ["uint8", "int128", "int256", "uint256"]


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_constant_list_fail(get_contract, assert_compile_failed, storage_type, return_type):
    code = f"""
MY_CONSTANT: constant({storage_type}[3]) = [1, 2, 3]

@external
def foo() -> {return_type}[3]:
    return MY_CONSTANT
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_constant_list_fail_2(get_contract, assert_compile_failed, storage_type, return_type):
    code = f"""
MY_CONSTANT: constant({storage_type}[3]) = [1, 2, 3]

@external
def foo() -> {return_type}:
    return MY_CONSTANT[0]
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_constant_list_fail_3(get_contract, assert_compile_failed, storage_type, return_type):
    code = f"""
MY_CONSTANT: constant({storage_type}[3]) = [1, 2, 3]

@external
def foo(i: uint256) -> {return_type}:
    return MY_CONSTANT[i]
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


def test_constant_list_address(get_contract, tx_failed):
    some_good_address = [
        "0x0000000000000000000000000000000000012345",
        "0x0000000000000000000000000000000000023456",
        "0x0000000000000000000000000000000000034567",
        "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
        "0xffffFFFfFFffffffffffffffFfFFFfffFFFfFFfE",
        "0xFfffFfFFFfFFFFfFFfFFFfFFFfFFfFFFfFfFfFf1",
    ]
    code = """
MY_LIST: constant(address[6]) = [
    0x0000000000000000000000000000000000012345,
    0x0000000000000000000000000000000000023456,
    0x0000000000000000000000000000000000034567,
    0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF,
    0xffffFFFfFFffffffffffffffFfFFFfffFFFfFFfE,
    0xFfffFfFFFfFFFFfFFfFFFfFFFfFFfFFFfFfFfFf1
]
@external
def ix(i: uint256) -> address:
    return MY_LIST[i]
    """
    c = get_contract(code)
    for i, p in enumerate(some_good_address):
        assert c.ix(i) == p
    # assert oob
    with tx_failed():
        c.ix(len(some_good_address) + 1)


def test_list_index_complex_expr(get_contract, tx_failed):
    # test subscripts where the index is not a literal
    code = """
@external
def foo(xs: uint256[257], i: uint8) -> uint256:
    return xs[i + 1]
    """
    c = get_contract(code)
    xs = [i + 1 for i in range(257)]

    for ix in range(255):
        assert c.foo(xs, ix) == xs[ix + 1]

    # safemath should fail for uint8: 255 + 1.
    with tx_failed():
        c.foo(xs, 255)


@pytest.mark.parametrize(
    "type,value",
    [
        ("decimal", [[5.0, 11.0], [17.0, 29.0], [37.0, 41.0]]),
        ("uint8", [[0, 1], [17, 250], [255, 2]]),
        ("int128", [[0, -1], [1, -(2**127)], [2**127 - 1, -50]]),
        ("int256", [[0, -1], [1, -(2**255)], [2**255 - 1, -50]]),
        ("uint256", [[0, 1], [2**8, 2**255 + 1], [2**256 - 1, 100]]),
        (
            "uint256",
            [
                [2**255 + 1, 2**255 + 2],
                [2**255 + 3, 2**255 + 4],
                [2**255 + 5, 2**255 + 6],
            ],
        ),
        ("bool", [[True, False], [True, False], [True, False]]),
    ],
)
def test_constant_nested_list(get_contract, tx_failed, type, value):
    code = f"""
MY_LIST: constant({type}[{len(value[0])}][{len(value)}]) = {value}
@external
def ix(i: uint256, j: uint256) -> {type}:
    return MY_LIST[i][j]
    """
    c = get_contract(code)
    for i, p in enumerate(value):
        for j, q in enumerate(p):
            assert c.ix(i, j) == q
    # assert oob
    with tx_failed():
        c.ix(len(value) + 1, len(value[0]) + 1)


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_constant_nested_list_fail(get_contract, assert_compile_failed, storage_type, return_type):
    code = f"""
MY_CONSTANT: constant({storage_type}[2][3]) = [[1, 2], [3, 4], [5, 6]]

@external
def foo() -> {return_type}[2][3]:
    return MY_CONSTANT
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_constant_nested_list_fail_2(
    get_contract, assert_compile_failed, storage_type, return_type
):
    code = f"""
MY_CONSTANT: constant({storage_type}[2][3]) = [[1, 2], [3, 4], [5, 6]]

@external
def foo() -> {return_type}:
    return MY_CONSTANT[0][0]
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)
