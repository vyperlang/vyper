import itertools

import pytest

from vyper.exceptions import ArrayIndexException, InvalidType, OverflowException, TypeMismatch


def test_list_tester_code(get_contract_with_gas_estimation):
    list_tester_code = """
z: DynArray[int128, 3]
z2: DynArray[DynArray[int128, 2], 2]
z3: DynArray[int128, 2]

@external
def foo(x: DynArray[int128, 3]) -> int128:
    return x[0] + x[1] + x[2]

@external
def goo(x: DynArray[DynArray[int128, 2], 2]) -> int128:
    return x[0][0] + x[0][1] + x[1][0] * 10 + x[1][1] * 10

@external
def hoo(x: DynArray[int128, 3]) -> int128:
    y: DynArray[int128, 3] = x
    return y[0] + x[1] + y[2]

@external
def joo(x: DynArray[DynArray[int128, 2], 2]) -> int128:
    y: DynArray[DynArray[int128, 2], 2] = x
    y2: DynArray[int128, 2] = x[1]
    return y[0][0] + y[0][1] + y2[0] * 10 + y2[1] * 10

@external
def koo(x: DynArray[int128, 3]) -> int128:
    self.z = x
    return self.z[0] + x[1] + self.z[2]

@external
def loo(x: DynArray[DynArray[int128, 2], 2]) -> int128:
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
z: DynArray[int128, 2]

@external
def foo() -> DynArray[int128, 2]:
    return [3, 5]

@external
def goo() -> DynArray[int128, 2]:
    x: DynArray[int128, 2] = [3, 5]
    return x

@external
def hoo() -> DynArray[int128, 2]:
    self.z = [3, 5]
    return self.z

@external
def hoo1() -> DynArray[int128, 2]:
    self.z = empty(DynArray[int128, 2])
    return self.z

@external
def hoo2() -> DynArray[int128, 2]:
    return empty(DynArray[int128, 2])

@external
def hoo3() -> DynArray[int128, 2]:
    return []

@external
def hoo4() -> DynArray[int128, 2]:
    self.z = []
    return self.z

@external
def hoo5() -> DynArray[DynArray[int128, 2], 2]:
    return []

@external
def joo() -> DynArray[int128, 2]:
    self.z = [3, 5]
    x: DynArray[int128, 2] = self.z
    return x

@external
def koo() -> DynArray[DynArray[int128, 2], 2]:
    return [[1, 2], [3, 4]]

@external
def loo() -> DynArray[DynArray[int128, 2], 2]:
    x: DynArray[DynArray[int128, 2], 2] = [[1, 2], [3, 4]]
    return x

@external
def moo() -> DynArray[DynArray[int128, 2], 2]:
    x: DynArray[int128, 2] = [1,2]
    return [x, [3,4]]

@external
def noo(inp: DynArray[int128, 2]) -> DynArray[int128, 2]:
    return inp

@external
def ooo(inp: DynArray[int128, 2]) -> DynArray[int128, 2]:
    self.z = inp
    return self.z

@external
def poo(inp: DynArray[DynArray[int128, 2], 2]) -> DynArray[DynArray[int128, 2], 2]:
    return inp

@external
def qoo(inp: DynArray[int128, 2]) -> DynArray[DynArray[int128, 2], 2]:
    return [inp, [3,4]]

@external
def roo(inp: DynArray[decimal, 2]) -> DynArray[DynArray[decimal, 2], 2]:
    return [inp, [3.0, 4.0]]
    """

    c = get_contract_with_gas_estimation(list_output_tester_code)
    assert c.foo() == [3, 5]
    assert c.goo() == [3, 5]
    assert c.hoo() == [3, 5]
    assert c.hoo1() == c.hoo2() == c.hoo3() == c.hoo4() == []
    assert c.hoo5() == []
    assert c.joo() == [3, 5]
    assert c.koo() == [[1, 2], [3, 4]]
    assert c.loo() == [[1, 2], [3, 4]]
    assert c.moo() == [[1, 2], [3, 4]]
    assert c.noo([]) == []
    assert c.noo([3, 5]) == [3, 5]
    assert c.ooo([]) == []
    assert c.ooo([3, 5]) == [3, 5]
    assert c.poo([]) == []
    assert c.poo([[1, 2], [3, 4]]) == [[1, 2], [3, 4]]
    assert c.qoo([1, 2]) == [[1, 2], [3, 4]]
    assert c.roo([1, 2]) == [[1.0, 2.0], [3.0, 4.0]]

    print("Passed list output tests")


def test_array_accessor(get_contract_with_gas_estimation):
    array_accessor = """
@external
def test_array(x: int128, y: int128, z: int128, w: int128) -> int128:
    a: DynArray[int128, 4] = [0, 0, 0, 0]
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
    a: DynArray[DynArray[int128, 2], 2] = [[0, 0], [0, 0]]
    a[0][0] = x
    a[0][1] = y
    a[1][0] = z
    a[1][1] = w
    return a[0][0] * 1000 + a[0][1] * 100 + a[1][0] * 10 + a[1][1]
    """

    c = get_contract_with_gas_estimation(two_d_array_accessor)
    assert c.test_array(2, 7, 1, 8) == 2718
    print("Passed complex array accessor test")


def test_returns_lists(get_contract_with_gas_estimation):
    code = """
@external
def test_array_num_return() -> DynArray[DynArray[int128, 2], 2]:
    a: DynArray[DynArray[int128, 2], 2] = [empty(DynArray[int128, 2]), [3, 4]]
    return a

@external
def test_array_decimal_return1() -> DynArray[DynArray[decimal, 2], 2]:
    a: DynArray[DynArray[decimal, 2], 2] = [[1.0], [3.0, 4.0]]
    return a

@external
def test_array_decimal_return2() -> DynArray[DynArray[decimal, 2], 2]:
    return [[1.0, 2.0]]

@external
def test_array_decimal_return3() -> DynArray[DynArray[decimal, 2], 2]:
    a: DynArray[DynArray[decimal, 2], 2] = [[1.0, 2.0], [3.0]]
    return a
"""

    c = get_contract_with_gas_estimation(code)
    assert c.test_array_num_return() == [[], [3, 4]]
    assert c.test_array_decimal_return1() == [[1.0], [3.0, 4.0]]
    assert c.test_array_decimal_return2() == [[1.0, 2.0]]
    assert c.test_array_decimal_return3() == [[1.0, 2.0], [3.0]]


def test_mult_list(get_contract_with_gas_estimation):
    code = """
nest3: DynArray[DynArray[DynArray[uint256, 2], 2], 2]
nest4: DynArray[DynArray[DynArray[DynArray[uint256, 2], 2], 2], 2]

@external
def test_multi3_1() -> DynArray[DynArray[DynArray[uint256, 2], 2], 2]:
    l: DynArray[DynArray[DynArray[uint256, 2], 2], 2] = [[[0, 0], [0, 4]], [[0, 7], [0, 123]]]
    self.nest3 = l
    return self.nest3

@external
def test_multi3_2() -> DynArray[DynArray[DynArray[uint256, 2], 2], 2]:
    l: DynArray[DynArray[DynArray[uint256, 2], 2], 2] = [[[0, 0], [0, 4]], [[0, 7], [0, 123]]]
    self.nest3 = l
    l = self.nest3
    return l

@external
def test_multi4_1() -> DynArray[DynArray[DynArray[DynArray[uint256, 2], 2], 2], 2]:
    l: DynArray[DynArray[DynArray[DynArray[uint256, 2], 2], 2], 2] = [[[[1, 0], [0, 4]], [[0, 0], [0, 0]]], [[[444, 0], [0, 0]],[[1, 0], [0, 222]]]]  # noqa: E501
    self.nest4 = l
    l = self.nest4
    return l

@external
def test_multi4_2() -> DynArray[DynArray[DynArray[DynArray[uint256, 2], 2], 2], 2]:
    l: DynArray[DynArray[DynArray[DynArray[uint256, 2], 2], 2], 2] = [[[[1, 0], [0, 4]], [[0, 0], [0, 0]]], [[[444, 0], [0, 0]],[[1, 0], [0, 222]]]]  # noqa: E501
    self.nest4 = l
    return self.nest4
    """

    c = get_contract_with_gas_estimation(code)

    nest3 = [[[0, 0], [0, 4]], [[0, 7], [0, 123]]]
    assert c.test_multi3_1() == nest3
    assert c.test_multi3_2() == nest3
    nest4 = [
        [[[1, 0], [0, 4]], [[0, 0], [0, 0]]],
        [[[444, 0], [0, 0]], [[1, 0], [0, 222]]],
    ]
    assert c.test_multi4_1() == nest4
    assert c.test_multi4_2() == nest4


def test_uint256_accessor(get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@external
def bounds_check_uint256(xs: DynArray[uint256, 3], ix: uint256) -> uint256:
    return xs[ix]
    """
    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.bounds_check_uint256([], 0))

    assert c.bounds_check_uint256([1], 0) == 1
    assert_tx_failed(lambda: c.bounds_check_uint256([1], 1))

    assert c.bounds_check_uint256([1, 2, 3], 0) == 1
    assert c.bounds_check_uint256([1, 2, 3], 2) == 3
    assert_tx_failed(lambda: c.bounds_check_uint256([1, 2, 3], 3))

    # TODO do bounds checks for nested darrays


@pytest.mark.parametrize("list_", ([], [11], [11, 12], [11, 12, 13]))
def test_dynarray_len(get_contract_with_gas_estimation, assert_tx_failed, list_):
    code = """
@external
def darray_len(xs: DynArray[uint256, 3]) -> uint256:
    return len(xs)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.darray_len(list_) == len(list_)


def test_dynarray_too_large(get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@external
def darray_len(xs: DynArray[uint256, 3]) -> uint256:
    return len(xs)
    """

    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.darray_len([1, 2, 3, 4]))


def test_int128_accessor(get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@external
def bounds_check_int128(ix: int128) -> uint256:
    xs: DynArray[uint256, 3] = [1,2,3]
    return xs[ix]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bounds_check_int128(0) == 1
    assert c.bounds_check_int128(2) == 3
    assert_tx_failed(lambda: c.bounds_check_int128(3))
    assert_tx_failed(lambda: c.bounds_check_int128(-1))


def test_list_check_heterogeneous_types(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@external
def fail() -> uint256:
    xs: DynArray[uint256, 3] = [1,2,3]
    return xs[3]
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ArrayIndexException)
    code = """
@external
def fail() -> uint256:
    xs: DynArray[uint256, 3] = [1,2,3]
    return xs[-1]
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ArrayIndexException)


def test_compile_time_bounds_check(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@external
def parse_list_fail():
    xs: DynArray[uint256, 3] = [2**256, 1, 3]
    pass
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), OverflowException)


def test_2d_array_input_1(get_contract):
    code = """
@internal
def test_input(
    arr: DynArray[DynArray[int128, 2], 1], i: int128
) -> (DynArray[DynArray[int128, 2], 1], int128):
    return arr, i

@external
def test_values(
    arr: DynArray[DynArray[int128, 2], 1], i: int128
) -> (DynArray[DynArray[int128, 2], 1], int128):
    return self.test_input(arr, i)
    """

    c = get_contract(code)
    assert c.test_values([[1, 2]], 3) == [[[1, 2]], 3]


def test_2d_array_input_2(get_contract):
    code = """
@internal
def test_input(
    arr: DynArray[DynArray[int128, 2], 3],
    s: String[10]
) -> (DynArray[DynArray[int128, 2], 3], String[10]):
    return arr, s

@external
def test_values(
    arr: DynArray[DynArray[int128, 2], 3],
    s: String[10]
) -> (DynArray[DynArray[int128, 2], 3], String[10]):
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
def outer() -> DynArray[int128, 2]:
    return [333, self.inner()[0]]
    """

    c = get_contract(code)
    assert c.outer() == [333, 1]


def test_nested_calls_inside_arrays(get_contract):
    code = """
@internal
def _foo(a: uint256, b: DynArray[uint256, 2]) -> (uint256, uint256, uint256, uint256, uint256):
    return 1, a, b[0], b[1], 5

@internal
def _foo2() -> uint256:
    a: DynArray[uint256, 10] = [6,7,8,9,10,11,12,13,15,16]
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
def _foo(
    a: DynArray[uint256, 2],
    b: DynArray[uint256, 2]
) -> (uint256, uint256, uint256, uint256, uint256):
    return a[1]-b[0], 2, a[0]-b[1], 8-b[1], 5

@internal
def _foo2() -> (uint256, uint256):
    a: DynArray[uint256, 10] = [6,7,8,9,10,11,12,13,15,16]
    return a[6], 4

@external
def foo() -> (uint256, uint256, uint256, uint256, uint256):
    return self._foo([7, self._foo2()[0]], [11, self._foo2()[1]])
    """

    c = get_contract(code)
    assert c.foo() == [1, 2, 3, 4, 5]


append_pop_tests = [
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    for x in xs:
        self.my_array.append(x)
    return self.my_array
    """,
        lambda xs: xs,
    ),
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    for x in xs:
        self.my_array.append(x)
    for x in xs:
        self.my_array.pop()
    return self.my_array
    """,
        lambda xs: [],
    ),
    # check order of evaluation.
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 5]) -> (DynArray[uint256, 5], uint256):
    for x in xs:
        self.my_array.append(x)
    return self.my_array, self.my_array.pop()
    """,
        lambda xs: None if len(xs) == 0 else [xs, xs[-1]],
    ),
    # check order of evaluation.
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 5]) -> (uint256, DynArray[uint256, 5]):
    for x in xs:
        self.my_array.append(x)
    return self.my_array.pop(), self.my_array
    """,
        lambda xs: None if len(xs) == 0 else [xs[-1], xs[:-1]],
    ),
    # test memory arrays
    (
        """
@external
def foo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    ys: DynArray[uint256, 5] = []
    i: uint256 = 0
    for x in xs:
        if i >= len(xs) - 1:
            break
        ys.append(x)
        i += 1

    return ys
    """,
        lambda xs: xs[:-1],
    ),
    # check overflow
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 6]) -> DynArray[uint256, 5]:
    for x in xs:
        self.my_array.append(x)
    return self.my_array
    """,
        lambda xs: None if len(xs) > 5 else xs,
    ),
    # pop to 0 elems
    (
        """
@external
def foo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    ys: DynArray[uint256, 5] = []
    for x in xs:
        ys.append(x)
    for x in xs:
        ys.pop()
    return ys
    """,
        lambda xs: [],
    ),
    # check underflow
    (
        """
@external
def foo(xs: DynArray[uint256, 5]) -> DynArray[uint256, 5]:
    ys: DynArray[uint256, 5] = []
    for x in xs:
        ys.append(x)
    for x in xs:
        ys.pop()
    ys.pop()  # fail
    return ys
    """,
        lambda xs: None,
    ),
    # check underflow
    (
        """
my_array: DynArray[uint256, 5]
@external
def foo(xs: DynArray[uint256, 5]) -> uint256:
    return self.my_array.pop()
    """,
        lambda xs: None,
    ),
]


@pytest.mark.parametrize("code,check_result", append_pop_tests)
# TODO change this to fuzz random data
@pytest.mark.parametrize("test_data", [[1, 2, 3, 4, 5][:i] for i in range(6)])
def test_append_pop(get_contract, assert_tx_failed, code, check_result, test_data):
    c = get_contract(code)
    expected_result = check_result(test_data)
    if expected_result is None:
        # None is sentinel to indicate txn should revert
        assert_tx_failed(lambda: c.foo(test_data))
    else:
        assert c.foo(test_data) == expected_result


append_pop_complex_tests = [
    (
        """
@external
def foo(x: {typ}) -> DynArray[{typ}, 2]:
    ys: DynArray[{typ}, 1] = []
    ys.append(x)
    return ys
    """,
        lambda x: [x],
    ),
    (
        """
my_array: DynArray[{typ}, 1]
@external
def foo(x: {typ}) -> DynArray[{typ}, 2]:
    self.my_array.append(x)
    self.my_array.append(x)  # fail
    return self.my_array
    """,
        lambda x: None,
    ),
    (
        """
my_array: DynArray[{typ}, 5]
@external
def foo(x: {typ}) -> (DynArray[{typ}, 5], {typ}):
    self.my_array.append(x)
    return self.my_array, self.my_array.pop()
    """,
        lambda x: [[x], x],
    ),
    (
        """
my_array: DynArray[{typ}, 5]
@external
def foo(x: {typ}) -> ({typ}, DynArray[{typ}, 5]):
    self.my_array.append(x)
    return self.my_array.pop(), self.my_array
    """,
        lambda x: [x, []],
    ),
    (
        """
my_array: DynArray[{typ}, 5]
@external
def foo(x: {typ}) -> {typ}:
    return self.my_array.pop()
    """,
        lambda x: None,
    ),
]


@pytest.mark.parametrize("code_template,check_result", append_pop_complex_tests)
@pytest.mark.parametrize(
    "subtype", ["uint256[3]", "DynArray[uint256,3]", "DynArray[uint8, 4]", "Foo"]
)
# TODO change this to fuzz random data
def test_append_pop_complex(get_contract, assert_tx_failed, code_template, check_result, subtype):
    code = code_template.format(typ=subtype)
    test_data = [1, 2, 3]
    if subtype == "Foo":
        test_data = tuple(test_data)
        struct_def = """
struct Foo:
    x: uint256
    y: uint256
    z: uint256
        """
        code = struct_def + "\n" + code

    c = get_contract(code)
    expected_result = check_result(test_data)
    if expected_result is None:
        # None is sentinel to indicate txn should revert
        assert_tx_failed(lambda: c.foo(test_data))
    else:
        assert c.foo(test_data) == expected_result


def test_so_many_things_you_should_never_do(get_contract):
    code = """
@internal
def _foo(a: DynArray[uint256, 2], b: DynArray[uint256, 2]) -> DynArray[uint256, 5]:
    return [a[1]-b[0], 2, a[0]-b[1], 8-b[1], 5]

@internal
def _foo2() -> (uint256, uint256):
    b: DynArray[uint256, 2] = [5, 8]
    a: DynArray[uint256, 10] = [6,7,8,9,10,11,12,13,self._foo([44,b[0]],b)[4],16]
    return a[6], 4

@external
def foo() -> (uint256, DynArray[uint256, 3], DynArray[uint256, 2]):
    x: DynArray[uint256, 3] = [
        1,
        14-self._foo2()[0],
        self._foo([7,self._foo2()[0]], [11,self._foo2()[1]])[2]
    ]
    return 666, x, [88, self._foo2()[0]]
    """
    c = get_contract(code)
    assert c.foo() == [666, [1, 2, 3], [88, 12]]


def test_list_of_structs_arg(get_contract):
    code = """
struct Foo:
    x: uint256
    y: uint256

@external
def bar(_baz: DynArray[Foo, 3]) -> uint256:
    sum: uint256 = 0
    for i in range(3):
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
def bar(_baz: DynArray[Foo, 3]) -> String[96]:
    return concat(_baz[0]._msg, _baz[1]._msg, _baz[2]._msg)
    """
    c = get_contract(code)
    c_input = [[i, msg] for i, msg in enumerate(("Hello ", "world", "!!!!"))]
    assert c.bar(c_input) == "Hello world!!!!"


def test_constant_list(get_contract, assert_tx_failed):
    some_good_primes = [5.0, 11.0, 17.0, 29.0, 37.0, 41.0]
    code = f"""
MY_LIST: constant(DynArray[decimal, 6]) = {some_good_primes}
@external
def ix(i: uint256) -> decimal:
    return MY_LIST[i]
    """
    c = get_contract(code)
    for i, p in enumerate(some_good_primes):
        assert c.ix(i) == p
    # assert oob
    assert_tx_failed(lambda: c.ix(len(some_good_primes) + 1))


# TODO test loops

# Would be nice to put this somewhere accessible, like in vyper.types or something
integer_types = ["uint8", "int128", "int256", "uint256"]


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_constant_list_fail(get_contract, assert_compile_failed, storage_type, return_type):
    code = f"""
MY_CONSTANT: constant(DynArray[{storage_type}, 3]) = [1, 2, 3]

@external
def foo() -> DynArray[{return_type}, 3]:
    return MY_CONSTANT
    """
    assert_compile_failed(lambda: get_contract(code), InvalidType)


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_constant_list_fail_2(get_contract, assert_compile_failed, storage_type, return_type):
    code = f"""
MY_CONSTANT: constant(DynArray[{storage_type}, 3]) = [1, 2, 3]

@external
def foo() -> {return_type}:
    return MY_CONSTANT[0]
    """
    assert_compile_failed(lambda: get_contract(code), InvalidType)


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_constant_list_fail_3(get_contract, assert_compile_failed, storage_type, return_type):
    code = f"""
MY_CONSTANT: constant(DynArray[{storage_type}, 3]) = [1, 2, 3]

@external
def foo(i: uint256) -> {return_type}:
    return MY_CONSTANT[i]
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)
