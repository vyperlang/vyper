from vyper.exceptions import ArrayIndexException, TypeMismatch


def test_list_tester_code(get_contract_with_gas_estimation):
    list_tester_code = """
z: int128[3]
z2: int128[2][2]
z3: int128[2]

@public
def foo(x: int128[3]) -> int128:
    return x[0] + x[1] + x[2]

@public
def goo(x: int128[2][2]) -> int128:
    return x[0][0] + x[0][1] + x[1][0] * 10 + x[1][1] * 10

@public
def hoo(x: int128[3]) -> int128:
    y: int128[3] = x
    return y[0] + x[1] + y[2]

@public
def joo(x: int128[2][2]) -> int128:
    y: int128[2][2] = x
    y2: int128[2] = x[1]
    return y[0][0] + y[0][1] + y2[0] * 10 + y2[1] * 10

@public
def koo(x: int128[3]) -> int128:
    self.z = x
    return self.z[0] + x[1] + self.z[2]

@public
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

@public
def foo() -> int128[2]:
    return [3, 5]

@public
def goo() -> int128[2]:
    x: int128[2] = [3, 5]
    return x

@public
def hoo() -> int128[2]:
    self.z = [3, 5]
    return self.z

@public
def joo() -> int128[2]:
    self.z = [3, 5]
    x: int128[2] = self.z
    return x

@public
def koo() -> int128[2][2]:
    return [[1, 2], [3, 4]]

@public
def loo() -> int128[2][2]:
    x: int128[2][2] = [[1, 2], [3, 4]]
    return x

@public
def moo() -> int128[2][2]:
    x: int128[2] = [1,2]
    return [x, [3,4]]

@public
def noo(inp: int128[2]) -> int128[2]:
    return inp

@public
def poo(inp: int128[2][2]) -> int128[2][2]:
    return inp

@public
def qoo(inp: int128[2]) -> int128[2][2]:
    return [inp, [3,4]]

@public
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
@public
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
    print('Passed basic array accessor test')


def test_two_d_array_accessor(get_contract_with_gas_estimation):
    two_d_array_accessor = """
@public
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
    print('Passed complex array accessor test')


def test_returns_lists(get_contract_with_gas_estimation):
    code = """
@public
def test_array_num_return() -> int128[2][2]:
    a: int128[2][2] = [[1, 2], [3, 4]]
    return a

@public
def test_array_decimal_return1() -> decimal[2][2]:
    a: decimal[2][2] = [[1.0, 2.0], [3.0, 4.0]]
    return a

@public
def test_array_decimal_return2() -> decimal[2][2]:
    return [[1.0, 2.0], [3.0, 4.0]]

@public
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
@public
def test_multi3() -> uint256[2][2][2]:
    l: uint256[2][2][2] = [[[0, 0], [0, 4]], [[0, 0], [0, 123]]]
    return l

@public
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
@public
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
@public
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
@public
def fail() -> uint256:
    xs: uint256[3] = [1,2,3]
    return xs[3]
    """
    assert_compile_failed(
            lambda: get_contract_with_gas_estimation(code),
            ArrayIndexException
            )
    code = """
@public
def fail() -> uint256:
    xs: uint256[3] = [1,2,3]
    return xs[-1]
    """
    assert_compile_failed(
            lambda: get_contract_with_gas_estimation(code),
            ArrayIndexException
            )


def test_compile_time_bounds_check(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@public
def parse_list_fail():
    xs: uint256[3] = [2**255, 1, 3]
    pass
    """
    assert_compile_failed(
            lambda: get_contract_with_gas_estimation(code),
            TypeMismatch
            )
