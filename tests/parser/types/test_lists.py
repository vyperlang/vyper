from vyper.exceptions import ArrayIndexException, OverflowException


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


def test_uint256_accessor(get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@external
def bounds_check_uint256(ix: uint256) -> uint256:
    xs: uint256[3] = [1,2,3]
    return xs[ix]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.bounds_check_uint256(0) == 1
    assert c.bounds_check_uint256(2) == 3
    assert_tx_failed(lambda: c.bounds_check_uint256(3))


def test_int128_accessor(get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@external
def bounds_check_int128(ix: int128) -> uint256:
    xs: uint256[3] = [1,2,3]
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
