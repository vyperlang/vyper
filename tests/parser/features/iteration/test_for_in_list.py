import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_basic_for_in_list():
    code = """
def data() -> num:
    s = [1, 2, 3, 4, 5, 6]
    for i in s:
        if i >= 3:
            return i
    return -1
    """

    c = get_contract(code)

    assert c.data() == 3


def test_basic_for_list_liter():
    code = """
def data() -> num:
    for i in [3, 5, 7, 9]:
        if i > 5:
            return i
    return -1
    """

    c = get_contract(code)

    assert c.data() == 7


def test_basic_for_list_storage():
    code = """
x: num[4]

def set():
    self.x = [3, 5, 7, 9]

def data() -> num:
    for i in self.x:
        if i > 5:
            return i
    return -1
    """

    c = get_contract(code)

    assert c.data() == -1
    assert c.set() is None
    assert c.data() == 7


def test_basic_for_list_address():
    code = """
def data() -> address:
    addresses = [
        0x7d577a597B2742b498Cb5Cf0C26cDCD726d39E6e,
        0x82A978B3f5962A5b0957d9ee9eEf472EE55B42F1,
        0xDCEceAF3fc5C0a63d195d69b1A90011B7B19650D
    ]
    count = 0
    for i in addresses:
        count += 1
        if count == 2:
            return i
    return 0x0000000000000000000000000000000000000000
    """

    c = get_contract(code)

    assert c.data() == "0x82a978b3f5962a5b0957d9ee9eef472ee55b42f1"


def test_basic_for_list_storage_address():
    code = """
addresses: address[3]

def set(i: num, val: address):
    self.addresses[i] = val

def ret(i: num) -> address:
    return self.addresses[i]

def iterate_return_second() -> address:
    count = 0
    for i in self.addresses:
        count += 1
        if count == 2:
            return i
    """

    c = get_contract(code)

    c.set(0, '0x82A978B3f5962A5b0957d9ee9eEf472EE55B42F1')
    c.set(1, '0x7d577a597B2742b498Cb5Cf0C26cDCD726d39E6e')
    c.set(2, '0xDCEceAF3fc5C0a63d195d69b1A90011B7B19650D')

    assert c.ret(1) == c.iterate_return_second() == "0x7d577a597b2742b498cb5cf0c26cdcd726d39e6e"


def test_basic_for_list_storage_decimal():
    code = """
readings: decimal[3]

def set(i: num, val: decimal):
    self.readings[i] = val

def ret(i: num) -> decimal:
    return self.readings[i]

def i_return(break_count: num) -> decimal:
    count = 0
    for i in self.readings:
        if count == break_count:
            return i
        count += 1
    """

    c = get_contract(code)

    c.set(0, 0.0001)
    c.set(1, 1.1)
    c.set(2, 2.2)

    assert c.ret(2) == c.i_return(2) == 2.2
    assert c.ret(1) == c.i_return(1) == 1.1
    assert c.ret(0) == c.i_return(0) == 0.0001
