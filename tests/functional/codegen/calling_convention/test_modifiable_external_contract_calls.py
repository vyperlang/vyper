import pytest

from vyper.compiler import compile_code
from vyper.exceptions import StructureException, SyntaxException, UnknownType


def test_external_contract_call_declaration_expr(get_contract, tx_failed):
    contract_1 = """
lucky: public(int128)

@external
def set_lucky(_lucky: int128) -> int128:
    self.lucky = _lucky
    return self.lucky
"""

    contract_2 = """
interface ModBar:
    def set_lucky(_lucky: int128) -> int128: nonpayable

interface ConstBar:
    def set_lucky(_lucky: int128) -> int128: view

modifiable_bar_contract: ModBar
static_bar_contract: ConstBar

@deploy
def __init__(contract_address: address):
    self.modifiable_bar_contract = ModBar(contract_address)
    self.static_bar_contract = ConstBar(contract_address)

@external
def modifiable_set_lucky(_lucky: int128):
    extcall self.modifiable_bar_contract.set_lucky(_lucky)

@external
def static_set_lucky(_lucky: int128):
    s: int128 = staticcall self.static_bar_contract.set_lucky(_lucky)
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2, *[c1.address])
    c2.modifiable_set_lucky(7, transact={})
    assert c1.lucky() == 7
    # Fails attempting a state change after a call to a static address
    with tx_failed():
        c2.static_set_lucky(5, transact={})
    assert c1.lucky() == 7


def test_external_contract_call_declaration_stmt(get_contract, tx_failed):
    contract_1 = """
lucky: public(int128)

@external
def set_lucky(_lucky: int128) -> int128:
    self.lucky = _lucky
    return self.lucky
"""

    contract_2 = """
interface ModBar:
    def set_lucky(_lucky: int128) -> int128: nonpayable

interface ConstBar:
    def set_lucky(_lucky: int128) -> int128: view

modifiable_bar_contract: ModBar
static_bar_contract: ConstBar

@deploy
def __init__(contract_address: address):
    self.modifiable_bar_contract = ModBar(contract_address)
    self.static_bar_contract = ConstBar(contract_address)

@external
def modifiable_set_lucky(_lucky: int128) -> int128:
    x: int128 = extcall self.modifiable_bar_contract.set_lucky(_lucky)
    return x

@external
def static_set_lucky(_lucky: int128):
    x:int128 = staticcall self.static_bar_contract.set_lucky(_lucky)
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2, *[c1.address])
    c2.modifiable_set_lucky(7, transact={})
    assert c1.lucky() == 7
    # Fails attempting a state change after a call to a static address
    with tx_failed():
        c2.static_set_lucky(5, transact={})
    assert c1.lucky() == 7


def test_multiple_contract_state_changes(get_contract, tx_failed):
    contract_1 = """
lucky: public(int128)

@external
def set_lucky(_lucky: int128) -> int128:
    self.lucky = _lucky
    return self.lucky
"""

    contract_2 = """
interface ModBar:
    def set_lucky(_lucky: int128) -> int128: nonpayable

interface ConstBar:
    def set_lucky(_lucky: int128) -> int128: view

modifiable_bar_contract: ModBar
static_bar_contract: ConstBar

@deploy
def __init__(contract_address: address):
    self.modifiable_bar_contract = ModBar(contract_address)
    self.static_bar_contract = ConstBar(contract_address)

@external
def modifiable_set_lucky(_lucky: int128) -> int128:
    return extcall self.modifiable_bar_contract.set_lucky(_lucky)

@external
def static_set_lucky(_lucky: int128) -> int128:
    return staticcall self.static_bar_contract.set_lucky(_lucky)
    """

    contract_3 = """
interface ModBar:
    def modifiable_set_lucky(_lucky: int128) -> int128: nonpayable
    def static_set_lucky(_lucky: int128) -> int128: nonpayable

interface ConstBar:
    def modifiable_set_lucky(_lucky: int128) -> int128: view
    def static_set_lucky(_lucky: int128) -> int128: view

modifiable_bar_contract: ModBar
static_bar_contract: ConstBar

@deploy
def __init__(contract_address: address):
    self.modifiable_bar_contract = ModBar(contract_address)
    self.static_bar_contract = ConstBar(contract_address)

@external
def modifiable_modifiable_set_lucky(_lucky: int128):
    extcall self.modifiable_bar_contract.modifiable_set_lucky(_lucky)

@external
def modifiable_static_set_lucky(_lucky: int128):
    extcall self.modifiable_bar_contract.static_set_lucky(_lucky)

@external
def static_static_set_lucky(_lucky: int128) -> int128:
    return staticcall self.static_bar_contract.static_set_lucky(_lucky)

@external
def static_modifiable_set_lucky(_lucky: int128) -> int128:
    return staticcall self.static_bar_contract.modifiable_set_lucky(_lucky)
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2, *[c1.address])
    c3 = get_contract(contract_3, *[c2.address])

    assert c1.lucky() == 0
    c3.modifiable_modifiable_set_lucky(7, transact={})
    assert c1.lucky() == 7
    with tx_failed():
        c3.modifiable_static_set_lucky(6, transact={})
    with tx_failed():
        c3.static_modifiable_set_lucky(6, transact={})
    with tx_failed():
        c3.static_static_set_lucky(6, transact={})
    assert c1.lucky() == 7


def test_address_can_returned_from_contract_type(get_contract):
    contract_1 = """
@external
def bar() -> int128:
    return 1
"""
    contract_2 = """
interface Bar:
    def bar() -> int128: view

bar_contract: public(Bar)

@external
def foo(contract_address: address):
    self.bar_contract = Bar(contract_address)

@external
def get_bar() -> int128:
    return staticcall self.bar_contract.bar()
"""
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    c2.foo(c1.address, transact={})
    assert c2.bar_contract() == c1.address
    assert c2.get_bar() == 1


def test_invalid_external_contract_call_declaration_1():
    contract_1 = """
interface Bar:
    def bar() -> int128: pass
    """

    with pytest.raises(StructureException):
        compile_code(contract_1)


def test_invalid_external_contract_call_declaration_2():
    contract_1 = """
interface Bar:
    def bar() -> int128: view

bar_contract: Boo

@external
def foo(contract_address: address) -> int128:
    self.bar_contract = Bar(contract_address)
    return self.bar_contract.bar()
    """

    with pytest.raises(UnknownType):
        compile_code(contract_1)


def test_invalid_if_external_contract_doesnt_exist():
    code = """
modifiable_bar_contract: Bar
    """

    with pytest.raises(UnknownType):
        compile_code(code)


def test_invalid_if_not_in_valid_global_keywords():
    code = """
interface Bar:
    def set_lucky(_lucky: int128): nonpayable

modifiable_bar_contract: trusted(Bar)
    """
    with pytest.raises(SyntaxException):
        compile_code(code)


def test_invalid_if_have_modifiability_not_declared():
    code = """
interface Bar:
    def set_lucky(_lucky: int128): pass
    """
    with pytest.raises(StructureException):
        compile_code(code)
