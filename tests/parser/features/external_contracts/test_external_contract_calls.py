from viper.exceptions import StructureException, VariableDeclarationException, InvalidTypeException


def test_external_contract_calls(get_contract_with_gas_estimation):
    contract_1 = """
@public
def foo(arg1: num) -> num:
    return arg1
    """

    c = get_contract_with_gas_estimation(contract_1)

    contract_2 = """
class Foo():
        def foo(arg1: num) -> num: pass

@public
def bar(arg1: address, arg2: num) -> num:
    return Foo(arg1).foo(arg2)
    """
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c2.bar(c.address, 1) == 1
    print('Successfully executed an external contract call')


def test_complicated_external_contract_calls(get_contract_with_gas_estimation):
    contract_1 = """
lucky: public(num)

@public
def __init__(_lucky: num):
    self.lucky = _lucky

@public
def foo() -> num:
    return self.lucky

@public
def array() -> bytes <= 3:
    return 'dog'
    """

    lucky_number = 7
    c = get_contract_with_gas_estimation(contract_1, args=[lucky_number])

    contract_2 = """
class Foo():
    def foo() -> num: pass
    def array() -> bytes <= 3: pass

@public
def bar(arg1: address) -> num:
    return Foo(arg1).foo()
    """
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c2.bar(c.address) == lucky_number
    print('Successfully executed a complicated external contract call')


def test_external_contract_calls_with_bytes(get_contract_with_gas_estimation):
    contract_1 = """
@public
def array() -> bytes <= 3:
    return 'dog'
    """

    c = get_contract_with_gas_estimation(contract_1)

    contract_2 = """
class Foo():
    def array() -> bytes <= 3: pass

@public
def get_array(arg1: address) -> bytes <= 3:
    return Foo(arg1).array()
"""

    c2 = get_contract_with_gas_estimation(contract_2)
    assert c2.get_array(c.address) == b'dog'


def test_external_contract_call_state_change(get_contract):
    contract_1 = """
lucky: public(num)

@public
def set_lucky(_lucky: num):
    self.lucky = _lucky
    """

    lucky_number = 7
    c = get_contract(contract_1)

    contract_2 = """
class Foo():
    def set_lucky(_lucky: num): pass

@public
def set_lucky(arg1: address, arg2: num):
    Foo(arg1).set_lucky(arg2)
    """
    c2 = get_contract(contract_2)

    assert c.get_lucky() == 0
    c2.set_lucky(c.address, lucky_number)
    assert c.get_lucky() == lucky_number
    print('Successfully executed an external contract call state change')


def test_constant_external_contract_call_cannot_change_state(assert_tx_failed, get_contract_with_gas_estimation):
    contract_1 = """
lucky: public(num)

@public
def set_lucky(_lucky: num) -> num:
    self.lucky = _lucky
    return _lucky
    """

    lucky_number = 7
    c = get_contract_with_gas_estimation(contract_1)

    contract_2 = """
class Foo():
    def set_lucky(_lucky: num) -> num: pass

@public
@constant
def set_lucky_expr(arg1: address, arg2: num):
    Foo(arg1).set_lucky(arg2)

@public
@constant
def set_lucky_stmt(arg1: address, arg2: num) -> num:
    return Foo(arg1).set_lucky(arg2)
    """
    c2 = get_contract_with_gas_estimation(contract_2)

    assert_tx_failed(lambda: c2.set_lucky_expr(c.address, lucky_number))
    assert_tx_failed(lambda: c2.set_lucky_stmt(c.address, lucky_number))
    print('Successfully tested an constant external contract call attempted state change')


def test_external_contract_can_be_changed_based_on_address(get_contract):
    contract_1 = """
lucky: public(num)

@public
def set_lucky(_lucky: num):
    self.lucky = _lucky
    """

    lucky_number_1 = 7
    c = get_contract(contract_1)

    contract_2 = """
lucky: public(num)

@public
def set_lucky(_lucky: num) -> num:
    self.lucky = _lucky
    return self.lucky
    """

    lucky_number_2 = 3
    c2 = get_contract(contract_2)

    contract_3 = """
class Foo():
    def set_lucky(_lucky: num): pass

@public
def set_lucky(arg1: address, arg2: num):
    Foo(arg1).set_lucky(arg2)
    """
    c3 = get_contract(contract_3)

    c3.set_lucky(c.address, lucky_number_1)
    c3.set_lucky(c2.address, lucky_number_2)
    assert c.get_lucky() == lucky_number_1
    assert c2.get_lucky() == lucky_number_2
    print('Successfully executed multiple external contract calls to different contracts based on address')


def test_external_contract_calls_with_public_globals(get_contract):
    contract_1 = """
lucky: public(num)

@public
def __init__(_lucky: num):
    self.lucky = _lucky
    """

    lucky_number = 7
    c = get_contract(contract_1, args=[lucky_number])

    contract_2 = """
class Foo():
    def get_lucky() -> num: pass

@public
def bar(arg1: address) -> num:
    return Foo(arg1).get_lucky()
    """
    c2 = get_contract(contract_2)

    assert c2.bar(c.address) == lucky_number
    print('Successfully executed an external contract call with public globals')


def test_external_contract_calls_with_multiple_contracts(get_contract):
    contract_1 = """
lucky: public(num)

@public
def __init__(_lucky: num):
    self.lucky = _lucky
    """

    lucky_number = 7
    c = get_contract(contract_1, args=[lucky_number])

    contract_2 = """
class Foo():
    def get_lucky() -> num: pass

magic_number: public(num)

@public
def __init__(arg1: address):
    self.magic_number = Foo(arg1).get_lucky()
    """

    c2 = get_contract(contract_2, args=[c.address])
    contract_3 = """
class Bar():
    def get_magic_number() -> num: pass

best_number: public(num)

@public
def __init__(arg1: address):
    self.best_number = Bar(arg1).get_magic_number()
    """

    c3 = get_contract(contract_3, args=[c2.address])
    assert c3.get_best_number() == lucky_number
    print('Successfully executed a multiple external contract calls')


def test_invalid_external_contract_call_to_the_same_contract(assert_tx_failed, get_contract):
    contract_1 = """
@public
def bar() -> num:
    return 1
    """

    contract_2 = """
class Bar():
    def bar() -> num: pass

@public
def bar() -> num:
    return 1

@public
def _stmt(x: address):
    Bar(x).bar()

@public
def _expr(x: address) -> num:
    return Bar(x).bar()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    c2._stmt(c1.address)
    c2._expr(c1.address)
    assert_tx_failed(lambda: c2._stmt(c2.address))
    assert_tx_failed(lambda: c2._expr(c2.address))


def test_invalid_nonexistent_contract_call(t, assert_tx_failed, get_contract):
    contract_1 = """
@public
def bar() -> num:
    return 1
    """

    contract_2 = """
class Bar():
    def bar() -> num: pass

@public
def foo(x: address) -> num:
    return Bar(x).bar()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    assert c2.foo(c1.address) == 1
    assert_tx_failed(lambda: c2.foo(t.a1))
    assert_tx_failed(lambda: c2.foo(t.a7))


def test_invalid_contract_reference_declaration(assert_tx_failed, get_contract):
    contract = """
class Bar():
    get_magic_number: 1

best_number: public(num)

@public
def __init__():
    pass
"""
    assert_tx_failed(lambda: get_contract(contract), exception=StructureException)


def test_invalid_contract_reference_call(assert_tx_failed, get_contract):
    contract = """
@public
def bar(arg1: address, arg2: num) -> num:
    return Foo(arg1).foo(arg2)
"""
    assert_tx_failed(lambda: get_contract(contract), exception=VariableDeclarationException)


def test_invalid_contract_reference_return_type(assert_tx_failed, get_contract):
    contract = """
class Foo():
    def foo(arg2: num) -> invalid: pass

@public
def bar(arg1: address, arg2: num) -> num:
    return Foo(arg1).foo(arg2)
"""
    assert_tx_failed(lambda: get_contract(contract), exception=InvalidTypeException)


def test_external_contracts_must_be_declared_first_1(assert_tx_failed, get_contract):
    contract = """

item: public(num)

class Foo():
    def foo(arg2: num) -> num: pass
"""
    assert_tx_failed(lambda: get_contract(contract), exception=StructureException)


def test_external_contracts_must_be_declared_first_2(assert_tx_failed, get_contract):
    contract = """

MyLog: __log__({})

class Foo():
    def foo(arg2: num) -> num: pass
"""
    assert_tx_failed(lambda: get_contract(contract), exception=StructureException)


def test_external_contracts_must_be_declared_first_3(assert_tx_failed, get_contract):
    contract = """
@public
def foo() -> num:
    return 1

class Foo():
    def foo(arg2: num) -> num: pass
"""
    assert_tx_failed(lambda: get_contract(contract), exception=StructureException)


def test_external_contract_call_declaration_expr(get_contract):
    contract_1 = """
@public
def bar() -> num:
    return 1
"""

    contract_2 = """
class Bar():
    def bar() -> num: pass

bar_contract: Bar

@public
def foo(contract_address: contract(Bar)) -> num:
    self.bar_contract = contract_address
    return self.bar_contract.bar()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    assert c2.foo(c1.address) == 1


def test_external_contract_call_declaration_stmt(get_contract):
    contract_1 = """
lucky: num

@public
def set_lucky(_lucky: num):
    self.lucky = _lucky

@public
def get_lucky() -> num:
    return self.lucky
"""

    contract_2 = """
class Bar():
    def set_lucky(arg1: num): pass
    def get_lucky() -> num: pass

bar_contract: Bar

@public
def set_lucky(contract_address: contract(Bar)):
    self.bar_contract = contract_address
    self.bar_contract.set_lucky(1)

@public
def get_lucky(contract_address: contract(Bar)) -> num:
    self.bar_contract = contract_address
    return self.bar_contract.get_lucky()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    assert c1.get_lucky() == 0
    assert c2.get_lucky(c1.address) == 0
    c1.set_lucky(6)
    assert c1.get_lucky() == 6
    assert c2.get_lucky(c1.address) == 6
    c2.set_lucky(c1.address)
    assert c1.get_lucky() == 1
    assert c2.get_lucky(c1.address) == 1


def test_complex_external_contract_call_declaration(get_contract_with_gas_estimation):
    contract_1 = """
@public
def get_lucky() -> num:
    return 1
"""

    contract_2 = """
@public
def get_lucky() -> num:
    return 2
"""

    contract_3 = """
class Bar():
    def set_lucky(arg1: num): pass
    def get_lucky() -> num: pass

bar_contract: Bar

@public
def set_contract(contract_address: contract(Bar)):
    self.bar_contract = contract_address

@public
def get_lucky() -> num:
    return self.bar_contract.get_lucky()
"""

    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)
    c3 = get_contract_with_gas_estimation(contract_3)
    assert c1.get_lucky() == 1
    assert c2.get_lucky() == 2
    c3.set_contract(c1.address)
    assert c3.get_lucky() == 1
    c3.set_contract(c2.address)
    assert c3.get_lucky() == 2


def test_address_can_returned_from_contract_type(get_contract, utils):
    contract_1 = """
@public
def bar() -> num:
    return 1
"""
    contract_2 = """
class Bar():
    def bar() -> num: pass

bar_contract: public(Bar)

@public
def foo(contract_address: contract(Bar)):
    self.bar_contract = contract_address

@public
def get_bar() -> num:
    return self.bar_contract.bar()
"""
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    c2.foo(c1.address)
    assert utils.remove_0x_head(c2.get_bar_contract()) == c1.address.hex()
    assert c2.get_bar() == 1


def test_invalid_external_contract_call_declaration_1(assert_compile_failed, get_contract):
    contract_1 = """
class Bar():
    def bar() -> num: pass

bar_contract: Bar

@public
def foo(contract_address: contract(Boo)) -> num:
    self.bar_contract = contract_address
    return self.bar_contract.bar()
    """

    assert_compile_failed(lambda: get_contract(contract_1), InvalidTypeException)


def test_invalid_external_contract_call_declaration_2(assert_compile_failed, get_contract):
    contract_1 = """
class Bar():
    def bar() -> num: pass

bar_contract: Boo

@public
def foo(contract_address: contract(Bar)) -> num:
    self.bar_contract = contract_address
    return self.bar_contract.bar()
    """

    assert_compile_failed(lambda: get_contract(contract_1), InvalidTypeException)
