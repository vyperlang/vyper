import pytest

from vyper.exceptions import (
    ArgumentException,
    StateAccessViolation,
    StructureException,
    UndeclaredDefinition,
    UnknownType,
)


def test_external_contract_calls(get_contract, get_contract_with_gas_estimation, memory_mocker):
    contract_1 = """
@external
def foo(arg1: int128) -> int128:
    return arg1
    """

    c = get_contract_with_gas_estimation(contract_1)

    contract_2 = """
interface Foo:
        def foo(arg1: int128) -> int128: view

@external
def bar(arg1: address, arg2: int128) -> int128:
    return Foo(arg1).foo(arg2)
    """
    c2 = get_contract(contract_2)

    assert c2.bar(c.address, 1) == 1
    print("Successfully executed an external contract call")


def test_complicated_external_contract_calls(
    get_contract, get_contract_with_gas_estimation, memory_mocker
):
    contract_1 = """
lucky: public(int128)

@external
def __init__(_lucky: int128):
    self.lucky = _lucky

@external
def foo() -> int128:
    return self.lucky

@external
def array() -> Bytes[3]:
    return b'dog'
    """

    lucky_number = 7
    c = get_contract_with_gas_estimation(contract_1, *[lucky_number])

    contract_2 = """
interface Foo:
    def foo() -> int128: nonpayable
    def array() -> Bytes[3]: view

@external
def bar(arg1: address) -> int128:
    return Foo(arg1).foo()
    """
    c2 = get_contract(contract_2)

    assert c2.bar(c.address) == lucky_number
    print("Successfully executed a complicated external contract call")


@pytest.mark.parametrize("length", [3, 32, 33, 64])
def test_external_contract_calls_with_bytes(get_contract, length, memory_mocker):
    contract_1 = f"""
@external
def array() -> Bytes[{length}]:
    return b'dog'
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def array() -> Bytes[3]: view

@external
def get_array(arg1: address) -> Bytes[3]:
    return Foo(arg1).array()
"""

    c2 = get_contract(contract_2)
    assert c2.get_array(c.address) == b"dog"


def test_bytes_too_long(get_contract, assert_tx_failed, memory_mocker):
    contract_1 = """
@external
def array() -> Bytes[4]:
    return b'doge'
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def array() -> Bytes[3]: view

@external
def get_array(arg1: address) -> Bytes[3]:
    return Foo(arg1).array()
"""

    c2 = get_contract(contract_2)
    assert_tx_failed(lambda: c2.get_array(c.address))


@pytest.mark.parametrize("a,b", [(3, 3), (4, 3), (3, 4), (32, 32), (33, 33), (64, 64)])
@pytest.mark.parametrize("actual", [3, 32, 64])
def test_tuple_with_bytes(get_contract, assert_tx_failed, a, b, actual, memory_mocker):
    contract_1 = f"""
@external
def array() -> (Bytes[{actual}], int128, Bytes[{actual}]):
    return b'dog', 255, b'cat'
    """

    c = get_contract(contract_1)

    contract_2 = f"""
interface Foo:
    def array() -> (Bytes[{a}], int128, Bytes[{b}]): view

@external
def get_array(arg1: address) -> (Bytes[{a}], int128, Bytes[{b}]):
    a: Bytes[{a}] = b""
    b: int128 = 0
    c: Bytes[{b}] = b""
    a, b, c = Foo(arg1).array()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.array() == [b"dog", 255, b"cat"]
    assert c2.get_array(c.address) == [b"dog", 255, b"cat"]


@pytest.mark.parametrize("a,b", [(18, 7), (18, 18), (19, 6), (64, 6), (7, 19)])
@pytest.mark.parametrize("c,d", [(19, 7), (64, 64)])
def test_tuple_with_bytes_too_long(get_contract, assert_tx_failed, a, c, b, d, memory_mocker):
    contract_1 = f"""
@external
def array() -> (Bytes[{c}], int128, Bytes[{d}]):
    return b'nineteen characters', 255, b'seven!!'
    """

    c = get_contract(contract_1)

    contract_2 = f"""
interface Foo:
    def array() -> (Bytes[{a}], int128, Bytes[{b}]): view

@external
def get_array(arg1: address) -> (Bytes[{a}], int128, Bytes[{b}]):
    a: Bytes[{a}] = b""
    b: int128 = 0
    c: Bytes[{b}] = b""
    a, b, c = Foo(arg1).array()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.array() == [b"nineteen characters", 255, b"seven!!"]
    assert_tx_failed(lambda: c2.get_array(c.address))


def test_tuple_with_bytes_too_long_two(get_contract, assert_tx_failed, memory_mocker):
    contract_1 = """
@external
def array() -> (Bytes[30], int128, Bytes[30]):
    return b'nineteen characters', 255, b'seven!!'
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def array() -> (Bytes[30], int128, Bytes[3]): view

@external
def get_array(arg1: address) -> (Bytes[30], int128, Bytes[3]):
    a: Bytes[30] = b""
    b: int128 = 0
    c: Bytes[3] = b""
    a, b, c = Foo(arg1).array()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.array() == [b"nineteen characters", 255, b"seven!!"]
    assert_tx_failed(lambda: c2.get_array(c.address))


def test_external_contract_call_state_change(get_contract, memory_mocker):
    contract_1 = """
lucky: public(int128)

@external
def set_lucky(_lucky: int128):
    self.lucky = _lucky
    """

    lucky_number = 7
    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def set_lucky(_lucky: int128): nonpayable

@external
def set_lucky(arg1: address, arg2: int128):
    Foo(arg1).set_lucky(arg2)
    """
    c2 = get_contract(contract_2)

    assert c.lucky() == 0
    c2.set_lucky(c.address, lucky_number, transact={})
    assert c.lucky() == lucky_number
    print("Successfully executed an external contract call state change")


def test_constant_external_contract_call_cannot_change_state(
    assert_compile_failed, get_contract_with_gas_estimation
):
    c = """
interface Foo:
    def set_lucky(_lucky: int128) -> int128: nonpayable

@external
@view
def set_lucky_expr(arg1: address, arg2: int128):
    Foo(arg1).set_lucky(arg2)

@external
@view
def set_lucky_stmt(arg1: address, arg2: int128) -> int128:
    return Foo(arg1).set_lucky(arg2)
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(c), StateAccessViolation)

    print("Successfully blocked an external contract call from a constant function")


def test_external_contract_can_be_changed_based_on_address(get_contract, memory_mocker):
    contract_1 = """
lucky: public(int128)

@external
def set_lucky(_lucky: int128):
    self.lucky = _lucky
    """

    lucky_number_1 = 7
    c = get_contract(contract_1)

    contract_2 = """
lucky: public(int128)

@external
def set_lucky(_lucky: int128) -> int128:
    self.lucky = _lucky
    return self.lucky
    """

    lucky_number_2 = 3
    c2 = get_contract(contract_2)

    contract_3 = """
interface Foo:
    def set_lucky(_lucky: int128): nonpayable

@external
def set_lucky(arg1: address, arg2: int128):
    Foo(arg1).set_lucky(arg2)
    """
    c3 = get_contract(contract_3)

    c3.set_lucky(c.address, lucky_number_1, transact={})
    c3.set_lucky(c2.address, lucky_number_2, transact={})
    assert c.lucky() == lucky_number_1
    assert c2.lucky() == lucky_number_2
    print(
        "Successfully executed multiple external contract calls to different "
        "contracts based on address"
    )


def test_external_contract_calls_with_public_globals(get_contract):
    contract_1 = """
lucky: public(int128)

@external
def __init__(_lucky: int128):
    self.lucky = _lucky
    """

    lucky_number = 7
    c = get_contract(contract_1, *[lucky_number])

    contract_2 = """
interface Foo:
    def lucky() -> int128: view

@external
def bar(arg1: address) -> int128:
    return Foo(arg1).lucky()
    """
    c2 = get_contract(contract_2)

    assert c2.bar(c.address) == lucky_number
    print("Successfully executed an external contract call with public globals")


def test_external_contract_calls_with_multiple_contracts(get_contract, memory_mocker):
    contract_1 = """
lucky: public(int128)

@external
def __init__(_lucky: int128):
    self.lucky = _lucky
    """

    lucky_number = 7
    c = get_contract(contract_1, *[lucky_number])

    contract_2 = """
interface Foo:
    def lucky() -> int128: view

magic_number: public(int128)

@external
def __init__(arg1: address):
    self.magic_number = Foo(arg1).lucky()
    """

    c2 = get_contract(contract_2, *[c.address])
    contract_3 = """
interface Bar:
    def magic_number() -> int128: view

best_number: public(int128)

@external
def __init__(arg1: address):
    self.best_number = Bar(arg1).magic_number()
    """

    c3 = get_contract(contract_3, *[c2.address])
    assert c3.best_number() == lucky_number
    print("Successfully executed a multiple external contract calls")


def test_invalid_external_contract_call_to_the_same_contract(assert_tx_failed, get_contract):
    contract_1 = """
@external
def bar() -> int128:
    return 1
    """

    contract_2 = """
interface Bar:
    def bar() -> int128: view

@external
def bar() -> int128:
    return 1

@external
def _stmt(x: address):
    Bar(x).bar()

@external
def _expr(x: address) -> int128:
    return Bar(x).bar()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    c2._stmt(c1.address)
    c2._stmt(c2.address)

    assert c2._expr(c1.address) == 1
    assert c2._expr(c2.address) == 1


def test_invalid_nonexistent_contract_call(w3, assert_tx_failed, get_contract):
    contract_1 = """
@external
def bar() -> int128:
    return 1
    """

    contract_2 = """
interface Bar:
    def bar() -> int128: view

@external
def foo(x: address) -> int128:
    return Bar(x).bar()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    assert c2.foo(c1.address) == 1
    assert_tx_failed(lambda: c2.foo(w3.eth.accounts[0]))
    assert_tx_failed(lambda: c2.foo(w3.eth.accounts[3]))


def test_invalid_contract_reference_declaration(assert_tx_failed, get_contract):
    contract = """
interface Bar:
    get_magic_number: 1

best_number: public(int128)

@external
def __init__():
    pass
"""
    assert_tx_failed(lambda: get_contract(contract), exception=StructureException)


def test_invalid_contract_reference_call(assert_tx_failed, get_contract):
    contract = """
@external
def bar(arg1: address, arg2: int128) -> int128:
    return Foo(arg1).foo(arg2)
"""
    assert_tx_failed(lambda: get_contract(contract), exception=UndeclaredDefinition)


def test_invalid_contract_reference_return_type(assert_tx_failed, get_contract):
    contract = """
interface Foo:
    def foo(arg2: int128) -> invalid: view

@external
def bar(arg1: address, arg2: int128) -> int128:
    return Foo(arg1).foo(arg2)
"""
    assert_tx_failed(lambda: get_contract(contract), exception=UnknownType)


def test_external_contract_call_declaration_expr(get_contract):
    contract_1 = """
@external
def bar() -> int128:
    return 1
"""

    contract_2 = """
interface Bar:
    def bar() -> int128: view

bar_contract: Bar

@external
def foo(contract_address: address) -> int128:
    self.bar_contract = Bar(contract_address)
    return self.bar_contract.bar()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    assert c2.foo(c1.address) == 1


def test_external_contract_call_declaration_stmt(get_contract):
    contract_1 = """
lucky: int128

@external
def set_lucky(_lucky: int128):
    self.lucky = _lucky

@external
def get_lucky() -> int128:
    return self.lucky
"""

    contract_2 = """
interface Bar:
    def set_lucky(arg1: int128): nonpayable
    def get_lucky() -> int128: view

bar_contract: Bar

@external
def set_lucky(contract_address: address):
    self.bar_contract = Bar(contract_address)
    self.bar_contract.set_lucky(1)

@external
def get_lucky(contract_address: address) -> int128:
    self.bar_contract = Bar(contract_address)
    return self.bar_contract.get_lucky()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    assert c1.get_lucky() == 0
    assert c2.get_lucky(c1.address) == 0
    c1.set_lucky(6, transact={})
    assert c1.get_lucky() == 6
    assert c2.get_lucky(c1.address) == 6
    c2.set_lucky(c1.address, transact={})
    assert c1.get_lucky() == 1
    assert c2.get_lucky(c1.address) == 1


def test_complex_external_contract_call_declaration(
    get_contract_with_gas_estimation, memory_mocker
):
    contract_1 = """
@external
def get_lucky() -> int128:
    return 1
"""

    contract_2 = """
@external
def get_lucky() -> int128:
    return 2
"""

    contract_3 = """
interface Bar:
    def set_lucky(arg1: int128): nonpayable
    def get_lucky() -> int128: view

bar_contract: Bar

@external
def set_contract(contract_address: address):
    self.bar_contract = Bar(contract_address)

@external
def get_lucky() -> int128:
    return self.bar_contract.get_lucky()
"""

    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)
    c3 = get_contract_with_gas_estimation(contract_3)
    assert c1.get_lucky() == 1
    assert c2.get_lucky() == 2
    c3.set_contract(c1.address, transact={})
    assert c3.get_lucky() == 1
    c3.set_contract(c2.address, transact={})
    assert c3.get_lucky() == 2


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
    return self.bar_contract.bar()
"""
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    c2.foo(c1.address, transact={})
    assert c2.bar_contract() == c1.address
    assert c2.get_bar() == 1


def test_invalid_external_contract_call_declaration_1(assert_compile_failed, get_contract):
    contract_1 = """
interface Bar:
    def bar() -> int128: view

bar_contract: Bar

@external
def foo(contract_address: contract(Boo)) -> int128:
    self.bar_contract = Bar(contract_address)
    return self.bar_contract.bar()
    """

    assert_compile_failed(lambda: get_contract(contract_1), UnknownType)


def test_invalid_external_contract_call_declaration_2(assert_compile_failed, get_contract):
    contract_1 = """
interface Bar:
    def bar() -> int128: view

bar_contract: Boo

@external
def foo(contract_address: address) -> int128:
    self.bar_contract = Bar(contract_address)
    return self.bar_contract.bar()
    """

    assert_compile_failed(lambda: get_contract(contract_1), UnknownType)


def test_external_with_payable_value(w3, get_contract_with_gas_estimation):
    contract_1 = """
@payable
@external
def get_lucky() -> int128:
    return 1

@external
def get_balance() -> uint256:
    return self.balance
"""

    contract_2 = """
interface Bar:
    def get_lucky() -> int128: payable

bar_contract: Bar

@external
def set_contract(contract_address: address):
    self.bar_contract = Bar(contract_address)

@payable
@external
def get_lucky(amount_to_send: uint256) -> int128:
    if amount_to_send != 0:
        return self.bar_contract.get_lucky(value=amount_to_send)
    else: # send it all
        return self.bar_contract.get_lucky(value=msg.value)
"""

    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    # Set address.
    assert c1.get_lucky() == 1
    assert c1.get_balance() == 0

    c2.set_contract(c1.address, transact={})

    # Send some eth
    assert c2.get_lucky(0, call={"value": 500}) == 1
    c2.get_lucky(0, transact={"value": 500})
    # Contract 1 received money.
    assert c1.get_balance() == 500
    assert w3.eth.getBalance(c1.address) == 500
    assert w3.eth.getBalance(c2.address) == 0

    # Send subset of amount
    assert c2.get_lucky(250, call={"value": 500}) == 1
    c2.get_lucky(250, transact={"value": 500})

    # Contract 1 received more money.
    assert c1.get_balance() == 750
    assert w3.eth.getBalance(c1.address) == 750
    assert w3.eth.getBalance(c2.address) == 250


def test_external_call_with_gas(assert_tx_failed, get_contract_with_gas_estimation):
    contract_1 = """
@external
def get_lucky() -> int128:
    return 656598
"""

    contract_2 = """
interface Bar:
    def set_lucky(arg1: int128): nonpayable
    def get_lucky() -> int128: view

bar_contract: Bar

@external
def set_contract(contract_address: address):
    self.bar_contract = Bar(contract_address)

@external
def get_lucky(gas_amount: uint256) -> int128:
    return self.bar_contract.get_lucky(gas=gas_amount)
"""

    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)
    c2.set_contract(c1.address, transact={})

    assert c2.get_lucky(1000) == 656598
    assert_tx_failed(lambda: c2.get_lucky(100))  # too little gas.


def test_invalid_keyword_on_call(assert_compile_failed, get_contract_with_gas_estimation):

    contract_1 = """
interface Bar:
    def set_lucky(arg1: int128): nonpayable
    def get_lucky() -> int128: view

bar_contract: Bar

@external
def get_lucky(amount_to_send: int128) -> int128:
    return self.bar_contract.get_lucky(gass=1)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(contract_1), ArgumentException)


def test_invalid_contract_declaration(assert_compile_failed, get_contract_with_gas_estimation):

    contract_1 = """
interface Bar:
    def set_lucky(arg1: int128): nonpayable

bar_contract: Barr

    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(contract_1), UnknownType)


FAILING_CONTRACTS_STRUCTURE_EXCEPTION = [
    """
# wrong arg count
interface Bar:
    def bar(arg1: int128) -> bool: view

@external
def foo(a: address):
    Bar(a).bar(1, 2)
    """,
    """
# expected args, none given
interface Bar:
    def bar(arg1: int128) -> bool: view

@external
def foo(a: address):
    Bar(a).bar()
    """,
    """
# expected no args, args given
interface Bar:
    def bar() -> bool: view

@external
def foo(a: address):
    Bar(a).bar(1)
    """,
]


@pytest.mark.parametrize("bad_code", FAILING_CONTRACTS_STRUCTURE_EXCEPTION)
def test_bad_code_struct_exc(assert_compile_failed, get_contract_with_gas_estimation, bad_code):

    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), ArgumentException)


def test_tuple_return_external_contract_call(get_contract, memory_mocker):
    contract_1 = """
@external
def out_literals() -> (int128, address, Bytes[10]):
    return 1, 0x0000000000000000000000000000000000000123, b"random"
    """

    contract_2 = """
interface Test:
    def out_literals() -> (int128, address, Bytes[10]) : view

@external
def test(addr: address) -> (int128, address, Bytes[10]):
    a: int128 = 0
    b: address = ZERO_ADDRESS
    c: Bytes[10] = b""
    (a, b, c) = Test(addr).out_literals()
    return a, b,c

    """
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    assert c1.out_literals() == [1, "0x0000000000000000000000000000000000000123", b"random"]
    assert c2.test(c1.address) == [1, "0x0000000000000000000000000000000000000123", b"random"]


def test_struct_return_external_contract_call_1(get_contract_with_gas_estimation):
    contract_1 = """
struct X:
    x: int128
    y: address
@external
def out_literals() -> X:
    return X({x: 1, y: 0x0000000000000000000000000000000000012345})
    """

    contract_2 = """
struct X:
    x: int128
    y: address
interface Test:
    def out_literals() -> X : view

@external
def test(addr: address) -> (int128, address):
    ret: X = Test(addr).out_literals()
    return ret.x, ret.y

    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.out_literals() == (1, "0x0000000000000000000000000000000000012345")
    assert c2.test(c1.address) == list(c1.out_literals())


@pytest.mark.parametrize("i,ln,s,", [(100, 6, "abcde"), (41, 40, "a" * 34), (57, 70, "z" * 68)])
def test_struct_return_external_contract_call_2(get_contract_with_gas_estimation, i, ln, s):
    contract_1 = f"""
struct X:
    x: int128
    y: String[{ln}]
    z: Bytes[{ln}]
@external
def get_struct_x() -> X:
    return X({{x: {i}, y: "{s}", z: b"{s}"}})
    """

    contract_2 = f"""
struct X:
    x: int128
    y: String[{ln}]
    z: Bytes[{ln}]
interface Test:
    def get_struct_x() -> X : view

@external
def test(addr: address) -> (int128, String[{ln}], Bytes[{ln}]):
    ret: X = Test(addr).get_struct_x()
    return ret.x, ret.y, ret.z

    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.get_struct_x() == (i, s, bytes(s, "utf-8"))
    assert c2.test(c1.address) == list(c1.get_struct_x())


def test_list_external_contract_call(get_contract, get_contract_with_gas_estimation):
    contract_1 = """
@external
def array() -> int128[3]:
    return [0, 0, 0]
    """

    c = get_contract_with_gas_estimation(contract_1)

    contract_2 = """
interface Foo:
    def array() -> int128[3]: view
@external
def get_array(arg1: address) -> int128[3]:
    return Foo(arg1).array()
"""

    c2 = get_contract(contract_2)
    assert c2.get_array(c.address) == [0, 0, 0]


def test_returndatasize_too_short(get_contract, assert_tx_failed):
    contract_1 = """
@external
def bar(a: int128) -> int128:
    return a
"""
    contract_2 = """
interface Bar:
    def bar(a: int128) -> (int128, int128): view

@external
def foo(_addr: address):
    Bar(_addr).bar(456)
"""
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    assert_tx_failed(lambda: c2.foo(c1.address))


def test_returndatasize_empty(get_contract, assert_tx_failed):
    contract_1 = """
@external
def bar(a: int128):
    pass
"""
    contract_2 = """
interface Bar:
    def bar(a: int128) -> int128: view

@external
def foo(_addr: address) -> int128:
    return Bar(_addr).bar(456)
"""
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    assert_tx_failed(lambda: c2.foo(c1.address))


def test_returndatasize_too_long(get_contract, assert_tx_failed):
    contract_1 = """
@external
def bar(a: int128) -> (int128, int128):
    return a, 789
"""
    contract_2 = """
interface Bar:
    def bar(a: int128) -> int128: view

@external
def foo(_addr: address) -> int128:
    return Bar(_addr).bar(456)
"""
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    # excess return data does not raise
    assert c2.foo(c1.address) == 456


def test_no_returndata(get_contract, assert_tx_failed):
    contract_1 = """
@external
def bar(a: int128) -> int128:
    return a
"""
    contract_2 = """
interface Bar:
    def bar(a: int128) -> int128: view

@external
def foo(_addr: address, _addr2: address) -> int128:
    x: int128 = Bar(_addr).bar(456)
    # make two calls to confirm EVM behavior: RETURNDATA is always based on the last call
    y: int128 = Bar(_addr2).bar(123)
    return y

"""
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    assert c2.foo(c1.address, c1.address) == 123
    assert_tx_failed(lambda: c2.foo(c1.address, "0x1234567890123456789012345678901234567890"))
