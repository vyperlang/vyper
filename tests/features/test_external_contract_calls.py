import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract

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
    """

    lucky_number = 7
    c = get_contract(contract_1, args=[lucky_number])

    contract_2 = """
class Foo():
    def foo() -> num: pass

def bar(arg1: address) -> num:
    return Foo(arg1).foo()
    """
    c2 = get_contract(contract_2)

    assert c2.bar(c.address) == lucky_number
    print('Successfully executed a complicated external contract call')


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
    print('Successfully executed a complicated external contract call')


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
