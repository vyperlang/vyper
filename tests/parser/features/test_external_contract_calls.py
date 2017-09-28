import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract, assert_tx_failed
from viper.exceptions import StructureException, VariableDeclarationException, InvalidTypeException

def test_external_contract_calls():
    contract_1 = """
def foo(arg1: num) -> num:
    return arg1
    """

    c = get_contract(contract_1)

    contract_2 = """
class Foo():
        def foo(arg1: num) -> num: pass

def bar(arg1: address, arg2: num) -> num:
    return Foo(arg1).foo(arg2)
    """
    c2 = get_contract(contract_2)

    assert c2.bar(c.address, 1) == 1
    print('Successfully executed an external contract call')


def test_complicated_external_contract_calls():
    contract_1 = """
lucky: public(num)

def __init__(_lucky: num):
    self.lucky = _lucky

def foo() -> num:
    return self.lucky

def array() -> bytes <= 3:
    return 'dog'
    """

    lucky_number = 7
    c = get_contract(contract_1, args=[lucky_number])

    contract_2 = """
class Foo():
    def foo() -> num: pass
    def array() -> bytes <= 3: pass

def bar(arg1: address) -> num:
    return Foo(arg1).foo()
    """
    c2 = get_contract(contract_2)

    assert c2.bar(c.address) == lucky_number
    print('Successfully executed a complicated external contract call')


def test_external_contract_calls_with_bytes():
    contract_1 = """
def array() -> bytes <= 3:
    return 'dog'
    """

    c = get_contract(contract_1)

    contract_2 = """
class Foo():
    def array() -> bytes <= 3: pass

def get_array(arg1: address) -> bytes <= 3:
    return Foo(arg1).array()
"""

    c2 = get_contract(contract_2)
    assert c2.get_array(c.address) == b'dog'


def test_external_contract_call__state_change():
    contract_1 = """
lucky: public(num)

def set_lucky(_lucky: num):
    self.lucky = _lucky
    """

    lucky_number = 7
    c = get_contract(contract_1)

    contract_2 = """
class Foo():
    def set_lucky(_lucky: num): pass

def set_lucky(arg1: address, arg2: num):
    Foo(arg1).set_lucky(arg2)
    """
    c2 = get_contract(contract_2)

    assert c.get_lucky() == 0
    c2.set_lucky(c.address, lucky_number)
    assert c.get_lucky() == lucky_number
    print('Successfully executed an external contract call state change')


def test_external_contract_can_be_changed_based_on_address():
    contract_1 = """
lucky: public(num)

def set_lucky(_lucky: num):
    self.lucky = _lucky
    """

    lucky_number_1 = 7
    c = get_contract(contract_1)

    contract_2 =  """
lucky: public(num)

def set_lucky(_lucky: num):
    self.lucky = _lucky
    """

    lucky_number_2 = 3
    c2 = get_contract(contract_1)

    contract_3 = """
class Foo():
    def set_lucky(_lucky: num): pass

def set_lucky(arg1: address, arg2: num):
    Foo(arg1).set_lucky(arg2)
    """
    c3 = get_contract(contract_3)

    c3.set_lucky(c.address, lucky_number_1)
    c3.set_lucky(c2.address, lucky_number_2)
    assert c.get_lucky() == lucky_number_1
    assert c2.get_lucky() == lucky_number_2
    print('Successfully executed multiple external contract calls to different contracts based on address')


def test_external_contract_calls_with_public_globals():
    contract_1 = """
lucky: public(num)

def __init__(_lucky: num):
    self.lucky = _lucky
    """

    lucky_number = 7
    c = get_contract(contract_1, args=[lucky_number])

    contract_2 = """
class Foo():
    def get_lucky() -> num: pass

def bar(arg1: address) -> num:
    return Foo(arg1).get_lucky()
    """
    c2 = get_contract(contract_2)

    assert c2.bar(c.address) == lucky_number
    print('Successfully executed an external contract call with public globals')


def test_external_contract_calls_with_multiple_contracts():
    contract_1 = """
lucky: public(num)

def __init__(_lucky: num):
    self.lucky = _lucky
    """

    lucky_number = 7
    c = get_contract(contract_1, args=[lucky_number])

    contract_2 = """
class Foo():
    def get_lucky() -> num: pass

magic_number: public(num)

def __init__(arg1: address):
    self.magic_number = Foo(arg1).get_lucky()
    """

    c2 = get_contract(contract_2, args=[c.address])
    contract_3 = """
class Bar():
    def get_magic_number() -> num: pass

best_number: public(num)

def __init__(arg1: address):
    self.best_number = Bar(arg1).get_magic_number()
    """

    c3 = get_contract(contract_3, args=[c2.address])
    assert c3.get_best_number() == lucky_number
    print('Successfully executed a multiple external contract calls')


def test_invalid_contract_reference_declaration(assert_tx_failed):
    contract = """
class Bar():
    get_magic_number: 1

best_number: public(num)

def __init__():
    pass
"""
    t.s = t.Chain()
    assert_tx_failed(t, lambda: get_contract(contract), exception = StructureException)


def test_invalid_contract_reference_call(assert_tx_failed):
    contract = """
def bar(arg1: address, arg2: num) -> num:
    return Foo(arg1).foo(arg2)
"""
    t.s = t.Chain()
    assert_tx_failed(t, lambda: get_contract(contract), exception = VariableDeclarationException)


def test_invalid_contract_reference_return_type(assert_tx_failed):
    contract = """
class Foo():
    def foo(arg2: num) -> invalid: pass

def bar(arg1: address, arg2: num) -> num:
    return Foo(arg1).foo(arg2)
"""
    t.s = t.Chain()
    assert_tx_failed(t, lambda: get_contract(contract), exception = InvalidTypeException)


def test_external_contracts_must_be_declared_first_1(assert_tx_failed):
    contract = """

item: public(num)

class Foo():
    def foo(arg2: num) -> num: pass
"""
    t.s = t.Chain()
    assert_tx_failed(t, lambda: get_contract(contract), exception = StructureException)


def test_external_contracts_must_be_declared_first_2(assert_tx_failed):
    contract = """

MyLog: __log__({})

class Foo():
    def foo(arg2: num) -> num: pass
"""
    t.s = t.Chain()
    assert_tx_failed(t, lambda: get_contract(contract), exception = StructureException)


def test_external_contracts_must_be_declared_first_3(assert_tx_failed):
    contract = """

def foo() -> num:
    return 1

class Foo():
    def foo(arg2: num) -> num: pass
"""
    t.s = t.Chain()
    assert_tx_failed(t, lambda: get_contract(contract), exception = StructureException)
