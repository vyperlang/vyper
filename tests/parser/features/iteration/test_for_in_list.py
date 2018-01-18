from viper.exceptions import StructureException, VariableDeclarationException


def test_basic_for_in_list(get_contract_with_gas_estimation):
    code = """
@public
def data() -> num:
    s: num[5] = [1, 2, 3, 4, 5, 6]
    for i in s:
        if i >= 3:
            return i
    return -1
    """

    c = get_contract_with_gas_estimation(code)

    assert c.data() == 3


def test_basic_for_list_liter(get_contract_with_gas_estimation):
    code = """
@public
def data() -> num:
    for i in [3, 5, 7, 9]:
        if i > 5:
            return i
    return -1
    """

    c = get_contract_with_gas_estimation(code)

    assert c.data() == 7


def test_basic_for_list_storage(get_contract_with_gas_estimation):
    code = """
x: num[4]

@public
def set():
    self.x = [3, 5, 7, 9]

@public
def data() -> num:
    for i in self.x:
        if i > 5:
            return i
    return -1
    """

    c = get_contract_with_gas_estimation(code)

    assert c.data() == -1
    assert c.set() is None
    assert c.data() == 7


def test_basic_for_list_address(get_contract_with_gas_estimation):
    code = """
@public
def data() -> address:
    addresses: address[3] = [
        0x7d577a597B2742b498Cb5Cf0C26cDCD726d39E6e,
        0x82A978B3f5962A5b0957d9ee9eEf472EE55B42F1,
        0xDCEceAF3fc5C0a63d195d69b1A90011B7B19650D
    ]
    count: num = 0
    for i in addresses:
        count += 1
        if count == 2:
            return i
    return 0x0000000000000000000000000000000000000000
    """

    c = get_contract_with_gas_estimation(code)

    assert c.data() == "0x82a978b3f5962a5b0957d9ee9eef472ee55b42f1"


def test_multiple_for_loops_1(get_contract_with_gas_estimation):
    code = """
@public
def foo(x: num):
    p: num = 0
    for i in range(3):
        p += i
    for i in range(4):
        p += i
"""
    get_contract_with_gas_estimation(code)


def test_multiple_for_loops_2(get_contract_with_gas_estimation):
    code = """
@public
def foo(x: num):
    p: num = 0
    for i in range(3):
        p += i
    for i in [1, 2, 3, 4]:
        p += i
"""
    get_contract_with_gas_estimation(code)


def test_multiple_for_loops_3(get_contract_with_gas_estimation):
    code = """
@public
def foo(x: num):
    p: num = 0
    for i in [1, 2, 3, 4]:
        p += i
    for i in [1, 2, 3, 4]:
        p += i
"""
    get_contract_with_gas_estimation(code)


def test_multiple_loops_4(get_contract_with_gas_estimation):
    code = """
@public
def foo():
    for i in range(10):
        pass
    for i in range(20):
        pass
"""
    get_contract_with_gas_estimation(code)


def test_using_index_variable_after_loop(get_contract_with_gas_estimation):
    code = """
@public
def foo():
    for i in range(10):
        pass
    i: num = 100  # create new variable i
    i = 200  # look up the variable i and check whether it is in forvars
"""
    get_contract_with_gas_estimation(code)


def test_basic_for_list_storage_address(get_contract_with_gas_estimation):
    code = """
addresses: address[3]

@public
def set(i: num, val: address):
    self.addresses[i] = val

@public
def ret(i: num) -> address:
    return self.addresses[i]

@public
def iterate_return_second() -> address:
    count: num = 0
    for i in self.addresses:
        count += 1
        if count == 2:
            return i
    """

    c = get_contract_with_gas_estimation(code)

    c.set(0, '0x82A978B3f5962A5b0957d9ee9eEf472EE55B42F1')
    c.set(1, '0x7d577a597B2742b498Cb5Cf0C26cDCD726d39E6e')
    c.set(2, '0xDCEceAF3fc5C0a63d195d69b1A90011B7B19650D')

    assert c.ret(1) == c.iterate_return_second() == "0x7d577a597b2742b498cb5cf0c26cdcd726d39e6e"


def test_basic_for_list_storage_decimal(get_contract_with_gas_estimation):
    code = """
readings: decimal[3]

@public
def set(i: num, val: decimal):
    self.readings[i] = val

@public
def ret(i: num) -> decimal:
    return self.readings[i]

@public
def i_return(break_count: num) -> decimal:
    count: num = 0
    for i in self.readings:
        if count == break_count:
            return i
        count += 1
    """

    c = get_contract_with_gas_estimation(code)

    c.set(0, 0.0001)
    c.set(1, 1.1)
    c.set(2, 2.2)

    assert c.ret(2) == c.i_return(2) == 2.2
    assert c.ret(1) == c.i_return(1) == 1.1
    assert c.ret(0) == c.i_return(0) == 0.0001


def test_altering_list_within_for_loop_1(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def data() -> num:
    s: num[6] = [1, 2, 3, 4, 5, 6]
    count: num = 0
    for i in s:
        s[count] = 1  # this should not be allowed.
        if i >= 3:
            return i
        count += 1
    return -1
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), StructureException)


def test_altering_list_within_for_loop_2(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo():
    s: num[6] = [1, 2, 3, 4, 5, 6]
    count: num = 0
    for i in s:
        s[count] += 1
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), StructureException)


def test_altering_list_within_for_loop_storage(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
s: num[6]

@public
def set():
    self.s = [1, 2, 3, 4, 5, 6]

@public
def data() -> num:
    count: num = 0
    for i in self.s:
        self.s[count] = 1  # this should not be allowed.
        if i >= 3:
            return i
        count += 1
    return -1
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), StructureException)


def test_invalid_nested_for_loop_1(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(x: num):
    for i in range(4):
        for i in range(5):
            pass
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), VariableDeclarationException)


def test_invalid_nested_for_loop_2(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(x: num):
    for i in [1,2]:
        for i in [1,2]:
            pass
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), VariableDeclarationException)


def test_invalid_iterator_assignment_1(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(x: num):
    for i in [1,2]:
        i = 2
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), StructureException)


def test_invalid_iterator_assignment_2(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(x: num):
    for i in [1,2]:
        i += 2
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), StructureException)
