from vyper.exceptions import StructureException, InvalidTypeException


def test_external_contract_call_declaration_expr(get_contract, assert_tx_failed):
    contract_1 = """
lucky: public(num)

@public
def set_lucky(_lucky: num):
    self.lucky = _lucky
"""

    contract_2 = """
class Bar():
    def set_lucky(_lucky: num): pass

modifiable_bar_contract: modifiable(Bar)
static_bar_contract: static(Bar)

@public
def __init__(contract_address: contract(Bar)):
    self.modifiable_bar_contract = contract_address
    self.static_bar_contract = contract_address

@public
def modifiable_set_lucky(_lucky: num):
    self.modifiable_bar_contract.set_lucky(_lucky)

@public
def static_set_lucky(_lucky: num):
    self.static_bar_contract.set_lucky(_lucky)
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2, args=[c1.address])
    c2.modifiable_set_lucky(7)
    assert c1.lucky() == 7
    # Fails attempting a state change after a call to a static address
    assert_tx_failed(lambda: c2.static_set_lucky(5))
    assert c1.lucky() == 7


def test_external_contract_call_declaration_stmt(get_contract, assert_tx_failed):
    contract_1 = """
lucky: public(num)

@public
def set_lucky(_lucky: num) -> num:
    self.lucky = _lucky
    return self.lucky
"""

    contract_2 = """
class Bar():
    def set_lucky(_lucky: num) -> num: pass

modifiable_bar_contract: modifiable(Bar)
static_bar_contract: static(Bar)

@public
def __init__(contract_address: contract(Bar)):
    self.modifiable_bar_contract = contract_address
    self.static_bar_contract = contract_address

@public
def modifiable_set_lucky(_lucky: num) -> num:
    x:num = self.modifiable_bar_contract.set_lucky(_lucky)
    return x

@public
def static_set_lucky(_lucky: num):
    x:num = self.static_bar_contract.set_lucky(_lucky)
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2, args=[c1.address])
    c2.modifiable_set_lucky(7)
    assert c1.lucky() == 7
    # Fails attempting a state change after a call to a static address
    assert_tx_failed(lambda: c2.static_set_lucky(5))
    assert c1.lucky() == 7


def test_multiple_contract_state_changes(get_contract, assert_tx_failed):
    contract_1 = """
lucky: public(num)

@public
def set_lucky(_lucky: num):
    self.lucky = _lucky
"""

    contract_2 = """
class Bar():
    def set_lucky(_lucky: num): pass

modifiable_bar_contract: modifiable(Bar)
static_bar_contract: static(Bar)

@public
def __init__(contract_address: contract(Bar)):
    self.modifiable_bar_contract = contract_address
    self.static_bar_contract = contract_address

@public
def modifiable_set_lucky(_lucky: num):
    self.modifiable_bar_contract.set_lucky(_lucky)

@public
def static_set_lucky(_lucky: num):
    self.static_bar_contract.set_lucky(_lucky)
"""

    contract_3 = """
class Bar():
    def modifiable_set_lucky(_lucky: num): pass
    def static_set_lucky(_lucky: num): pass

modifiable_bar_contract: modifiable(Bar)
static_bar_contract: static(Bar)

@public
def __init__(contract_address: contract(Bar)):
    self.modifiable_bar_contract = contract_address
    self.static_bar_contract = contract_address

@public
def modifiable_modifiable_set_lucky(_lucky: num):
    self.modifiable_bar_contract.modifiable_set_lucky(_lucky)

@public
def modifiable_static_set_lucky(_lucky: num):
    self.modifiable_bar_contract.static_set_lucky(_lucky)

@public
def static_static_set_lucky(_lucky: num):
    self.static_bar_contract.static_set_lucky(_lucky)

@public
def static_modifiable_set_lucky(_lucky: num):
    self.static_bar_contract.modifiable_set_lucky(_lucky)
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2, args=[c1.address])
    c3 = get_contract(contract_3, args=[c2.address])

    assert c1.lucky() == 0
    c3.modifiable_modifiable_set_lucky(7)
    assert c1.lucky() == 7
    assert_tx_failed(lambda: c3.modifiable_static_set_lucky(6))
    assert_tx_failed(lambda: c3.static_modifiable_set_lucky(6))
    assert_tx_failed(lambda: c3.static_static_set_lucky(6))
    assert c1.lucky() == 7


def test_address_can_returned_from_contract_type(get_contract, utils):
    contract_1 = """
@public
def bar() -> num:
    return 1
"""
    contract_2 = """
class Bar():
    def bar() -> num: pass

bar_contract: public(static(Bar))

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
    assert utils.remove_0x_head(c2.bar_contract()) == c1.address.hex()
    assert c2.get_bar() == 1


def test_invalid_external_contract_call_declaration_1(assert_compile_failed, get_contract):
    contract_1 = """
class Bar():
    def bar() -> num: pass

bar_contract: static(Bar)

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

bar_contract: static(Boo)

@public
def foo(contract_address: contract(Bar)) -> num:
    self.bar_contract = contract_address
    return self.bar_contract.bar()
    """

    assert_compile_failed(lambda: get_contract(contract_1), InvalidTypeException)


def test_invalid_if_external_contract_doesnt_exist(get_contract, assert_compile_failed):
    code = """
modifiable_bar_contract: modifiable(Bar)
"""

    assert_compile_failed(lambda: get_contract(code), InvalidTypeException)


def test_invalid_if_not_in_valid_global_keywords(get_contract, assert_compile_failed):
    code = """
class Bar():
    def set_lucky(_lucky: num): pass

modifiable_bar_contract: trusted(Bar)
    """
    assert_compile_failed(lambda: get_contract(code), StructureException)


def test_invalid_if_have_modifiability_not_declared(get_contract_with_gas_estimation_for_constants, assert_compile_failed):
    code = """
class Bar():
    def set_lucky(_lucky: num): pass

modifiable_bar_contract: public(Bar)
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation_for_constants(code), StructureException)
