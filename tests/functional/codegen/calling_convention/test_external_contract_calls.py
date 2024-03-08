from decimal import Decimal

import pytest
from eth.codecs import abi

from vyper import compile_code
from vyper.exceptions import (
    ArgumentException,
    InvalidType,
    StateAccessViolation,
    StructureException,
    UndeclaredDefinition,
    UnknownType,
)


def test_external_contract_calls(get_contract, get_contract_with_gas_estimation):
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
    return staticcall Foo(arg1).foo(arg2)
    """
    c2 = get_contract(contract_2)

    assert c2.bar(c.address, 1) == 1
    print("Successfully executed an external contract call")


def test_complicated_external_contract_calls(get_contract, get_contract_with_gas_estimation):
    contract_1 = """
lucky: public(int128)

@deploy
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
    return extcall Foo(arg1).foo()
    """
    c2 = get_contract(contract_2)

    assert c2.bar(c.address) == lucky_number
    print("Successfully executed a complicated external contract call")


@pytest.mark.parametrize("length", [3, 32, 33, 64])
def test_external_contract_calls_with_bytes(get_contract, length):
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
    return staticcall Foo(arg1).array()
"""

    c2 = get_contract(contract_2)
    assert c2.get_array(c.address) == b"dog"


def test_bytes_too_long(get_contract, tx_failed):
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
    return staticcall Foo(arg1).array()
"""

    c2 = get_contract(contract_2)
    with tx_failed():
        c2.get_array(c.address)


@pytest.mark.parametrize(
    "revert_string", ["Mayday, mayday!", "A very long revert string" + "." * 512]
)
def test_revert_propagation(get_contract, tx_failed, revert_string):
    raiser = f"""
@external
def run(x: bool) -> uint256:
    if x:
        raise "{revert_string}"
    return 123
    """
    caller = """
interface Raises:
    def run(x: bool) -> uint256: pure

@external
def run(raiser: address):
    a: uint256 = staticcall Raises(raiser).run(True)
    """
    c1 = get_contract(raiser)
    c2 = get_contract(caller)
    with tx_failed(exc_text=revert_string):
        c2.run(c1.address)


@pytest.mark.parametrize("a,b", [(3, 3), (4, 3), (3, 4), (32, 32), (33, 33), (64, 64)])
@pytest.mark.parametrize("actual", [3, 32, 64])
def test_tuple_with_bytes(get_contract, a, b, actual):
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
    a, b, c = staticcall Foo(arg1).array()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.array() == [b"dog", 255, b"cat"]
    assert c2.get_array(c.address) == [b"dog", 255, b"cat"]


@pytest.mark.parametrize("a,b", [(18, 7), (18, 18), (19, 6), (64, 6), (7, 19)])
@pytest.mark.parametrize("c,d", [(19, 7), (64, 64)])
def test_tuple_with_bytes_too_long(get_contract, tx_failed, a, c, b, d):
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
    a, b, c = staticcall Foo(arg1).array()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.array() == [b"nineteen characters", 255, b"seven!!"]
    with tx_failed():
        c2.get_array(c.address)


def test_tuple_with_bytes_too_long_two(get_contract, tx_failed):
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
    a, b, c = staticcall Foo(arg1).array()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.array() == [b"nineteen characters", 255, b"seven!!"]
    with tx_failed():
        c2.get_array(c.address)


@pytest.mark.parametrize("length", [8, 256])
def test_external_contract_calls_with_uint8(get_contract, length):
    contract_1 = f"""
@external
def foo() -> uint{length}:
    return 255
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> uint8: view

@external
def bar(arg1: address) -> uint8:
    return staticcall Foo(arg1).foo()
"""

    c2 = get_contract(contract_2)
    assert c2.bar(c.address) == 255


def test_uint8_too_long(get_contract, tx_failed):
    contract_1 = """
@external
def foo() -> uint256:
    return 2**255
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> uint8: view

@external
def bar(arg1: address) -> uint8:
    return staticcall Foo(arg1).foo()
"""

    c2 = get_contract(contract_2)
    with tx_failed():
        c2.bar(c.address)


@pytest.mark.parametrize("a,b", [(8, 8), (8, 256), (256, 8), (256, 256)])
@pytest.mark.parametrize("actual", [8, 256])
def test_tuple_with_uint8(get_contract, a, b, actual):
    contract_1 = f"""
@external
def foo() -> (uint{actual}, Bytes[3], uint{actual}):
    return 255, b'dog', 255
    """

    c = get_contract(contract_1)

    contract_2 = f"""
interface Foo:
    def foo() -> (uint{a}, Bytes[3], uint{b}): view

@external
def bar(arg1: address) -> (uint{a}, Bytes[3], uint{b}):
    a: uint{a} = 0
    b: Bytes[3] = b""
    c: uint{b} = 0
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [255, b"dog", 255]
    assert c2.bar(c.address) == [255, b"dog", 255]


@pytest.mark.parametrize("a,b", [(8, 256), (256, 8), (256, 256)])
def test_tuple_with_uint8_too_long(get_contract, tx_failed, a, b):
    contract_1 = f"""
@external
def foo() -> (uint{a}, Bytes[3], uint{b}):
    return {(2**a)-1}, b'dog', {(2**b)-1}
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> (uint8, Bytes[3], uint8): view

@external
def bar(arg1: address) -> (uint8, Bytes[3], uint8):
    a: uint8 = 0
    b: Bytes[3] = b""
    c: uint8 = 0
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [int(f"{(2**a)-1}"), b"dog", int(f"{(2**b)-1}")]
    with tx_failed():
        c2.bar(c.address)


@pytest.mark.parametrize("a,b", [(8, 256), (256, 8)])
def test_tuple_with_uint8_too_long_two(get_contract, tx_failed, a, b):
    contract_1 = f"""
@external
def foo() -> (uint{b}, Bytes[3], uint{a}):
    return {(2**b)-1}, b'dog', {(2**a)-1}
    """

    c = get_contract(contract_1)

    contract_2 = f"""
interface Foo:
    def foo() -> (uint{a}, Bytes[3], uint{b}): view

@external
def bar(arg1: address) -> (uint{a}, Bytes[3], uint{b}):
    a: uint{a} = 0
    b: Bytes[3] = b""
    c: uint{b} = 0
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [int(f"{(2**b)-1}"), b"dog", int(f"{(2**a)-1}")]
    with tx_failed():
        c2.bar(c.address)


@pytest.mark.parametrize("length", [128, 256])
def test_external_contract_calls_with_int128(get_contract, length):
    contract_1 = f"""
@external
def foo() -> int{length}:
    return 1
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> int128: view

@external
def bar(arg1: address) -> int128:
    return staticcall Foo(arg1).foo()
"""

    c2 = get_contract(contract_2)
    assert c2.bar(c.address) == 1


def test_int128_too_long(get_contract, tx_failed):
    contract_1 = """
@external
def foo() -> int256:
    return max_value(int256)
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> int128: view

@external
def bar(arg1: address) -> int128:
    return staticcall Foo(arg1).foo()
"""

    c2 = get_contract(contract_2)
    with tx_failed():
        c2.bar(c.address)


@pytest.mark.parametrize("a,b", [(128, 128), (128, 256), (256, 128), (256, 256)])
@pytest.mark.parametrize("actual", [128, 256])
def test_tuple_with_int128(get_contract, a, b, actual):
    contract_1 = f"""
@external
def foo() -> (int{actual}, Bytes[3], int{actual}):
    return 255, b'dog', 255
    """

    c = get_contract(contract_1)

    contract_2 = f"""
interface Foo:
    def foo() -> (int{a}, Bytes[3], int{b}): view

@external
def bar(arg1: address) -> (int{a}, Bytes[3], int{b}):
    a: int{a} = 0
    b: Bytes[3] = b""
    c: int{b} = 0
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [255, b"dog", 255]
    assert c2.bar(c.address) == [255, b"dog", 255]


@pytest.mark.parametrize("a,b", [(128, 256), (256, 128), (256, 256)])
def test_tuple_with_int128_too_long(get_contract, tx_failed, a, b):
    contract_1 = f"""
@external
def foo() -> (int{a}, Bytes[3], int{b}):
    return {(2**(a-1))-1}, b'dog', {(2**(b-1))-1}
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> (int128, Bytes[3], int128): view

@external
def bar(arg1: address) -> (int128, Bytes[3], int128):
    a: int128 = 0
    b: Bytes[3] = b""
    c: int128 = 0
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [int(f"{(2**(a-1))-1}"), b"dog", int(f"{(2**(b-1))-1}")]
    with tx_failed():
        c2.bar(c.address)


@pytest.mark.parametrize("a,b", [(128, 256), (256, 128)])
def test_tuple_with_int128_too_long_two(get_contract, tx_failed, a, b):
    contract_1 = f"""
@external
def foo() -> (int{b}, Bytes[3], int{a}):
    return {(2**(b-1))-1}, b'dog', {(2**(a-1))-1}
    """

    c = get_contract(contract_1)

    contract_2 = f"""
interface Foo:
    def foo() -> (int{a}, Bytes[3], int{b}): view

@external
def bar(arg1: address) -> (int{a}, Bytes[3], int{b}):
    a: int{a} = 0
    b: Bytes[3] = b""
    c: int{b} = 0
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [int(f"{(2**(b-1))-1}"), b"dog", int(f"{(2**(a-1))-1}")]
    with tx_failed():
        c2.bar(c.address)


@pytest.mark.parametrize("type", ["uint8", "uint256", "int128", "int256"])
def test_external_contract_calls_with_decimal(get_contract, type):
    contract_1 = f"""
@external
def foo() -> {type}:
    return 1
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> decimal: view

@external
def bar(arg1: address) -> decimal:
    return staticcall Foo(arg1).foo()
"""

    c2 = get_contract(contract_2)
    assert c2.bar(c.address) == Decimal("1e-10")


def test_decimal_too_long(get_contract, tx_failed):
    contract_1 = """
@external
def foo() -> uint256:
    return 2**255
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> decimal: view

@external
def bar(arg1: address) -> decimal:
    return staticcall Foo(arg1).foo()
"""

    c2 = get_contract(contract_2)
    with tx_failed():
        c2.bar(c.address)


@pytest.mark.parametrize("a", ["uint8", "uint256", "int128", "int256"])
@pytest.mark.parametrize("b", ["uint8", "uint256", "int128", "int256"])
def test_tuple_with_decimal(get_contract, a, b):
    contract_1 = f"""
@external
def foo() -> ({a}, Bytes[3], {b}):
    return 0, b'dog', 1
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> (decimal, Bytes[3], decimal): view

@external
def bar(arg1: address) -> (decimal, Bytes[3], decimal):
    a: decimal = 0.0
    b: Bytes[3] = b""
    c: decimal = 0.0
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
    """

    c2 = get_contract(contract_2)
    assert c.foo() == [0, b"dog", 1]
    result = c2.bar(c.address)
    assert result == [Decimal("0.0"), b"dog", Decimal("1e-10")]


@pytest.mark.parametrize("a,b", [(8, 256), (256, 8), (256, 256)])
def test_tuple_with_decimal_too_long(get_contract, tx_failed, a, b):
    contract_1 = f"""
@external
def foo() -> (uint{a}, Bytes[3], uint{b}):
    return {2**(a-1)}, b'dog', {2**(b-1)}
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> (decimal, Bytes[3], decimal): view

@external
def bar(arg1: address) -> (decimal, Bytes[3], decimal):
    a: decimal = 0.0
    b: Bytes[3] = b""
    c: decimal = 0.0
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [2 ** (a - 1), b"dog", 2 ** (b - 1)]
    with tx_failed():
        c2.bar(c.address)


@pytest.mark.parametrize("type", ["uint8", "uint256", "int128", "int256"])
def test_external_contract_calls_with_bool(get_contract, type):
    contract_1 = f"""
@external
def foo() -> {type}:
    return 1
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> bool: view

@external
def bar(arg1: address) -> bool:
    return staticcall Foo(arg1).foo()
    """

    c2 = get_contract(contract_2)
    assert c2.bar(c.address) is True


def test_bool_too_long(get_contract, tx_failed):
    contract_1 = """
@external
def foo() -> uint256:
    return 2
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> bool: view

@external
def bar(arg1: address) -> bool:
    return staticcall Foo(arg1).foo()
    """

    c2 = get_contract(contract_2)
    with tx_failed():
        c2.bar(c.address)


@pytest.mark.parametrize("a", ["uint8", "uint256", "int128", "int256"])
@pytest.mark.parametrize("b", ["uint8", "uint256", "int128", "int256"])
def test_tuple_with_bool(get_contract, a, b):
    contract_1 = f"""
@external
def foo() -> ({a}, Bytes[3], {b}):
    return 1, b'dog', 0
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> (bool, Bytes[3], bool): view

@external
def bar(arg1: address) -> (bool, Bytes[3], bool):
    a: bool = False
    b: Bytes[3] = b""
    c: bool = False
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [1, b"dog", 0]
    assert c2.bar(c.address) == [True, b"dog", False]


@pytest.mark.parametrize("a", ["uint8", "uint256", "int128", "int256"])
@pytest.mark.parametrize("b", ["uint8", "uint256", "int128", "int256"])
def test_tuple_with_bool_too_long(get_contract, tx_failed, a, b):
    contract_1 = f"""
@external
def foo() -> ({a}, Bytes[3], {b}):
    return 1, b'dog', 2
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> (bool, Bytes[3], bool): view

@external
def bar(arg1: address) -> (bool, Bytes[3], bool):
    a: bool = False
    b: Bytes[3] = b""
    c: bool = False
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [1, b"dog", 2]
    with tx_failed():
        c2.bar(c.address)


@pytest.mark.parametrize("type", ["uint8", "int128", "uint256", "int256"])
def test_external_contract_calls_with_address(get_contract, type):
    contract_1 = f"""
@external
def foo() -> {type}:
    return 1
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> address: view

@external
def bar(arg1: address) -> address:
    return staticcall Foo(arg1).foo()
"""

    c2 = get_contract(contract_2)
    assert c2.bar(c.address) == "0x0000000000000000000000000000000000000001"


@pytest.mark.parametrize("type", ["uint256", "int256"])
def test_external_contract_calls_with_address_two(get_contract, type):
    contract_1 = f"""
@external
def foo() -> {type}:
    return (2**160)-1
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> address: view

@external
def bar(arg1: address) -> address:
    return staticcall Foo(arg1).foo()
"""

    c2 = get_contract(contract_2)
    assert c2.bar(c.address).lower() == "0xffffffffffffffffffffffffffffffffffffffff"


@pytest.mark.parametrize("type", ["uint256", "int256"])
def test_address_too_long(get_contract, tx_failed, type):
    contract_1 = f"""
@external
def foo() -> {type}:
    return 2**160
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> address: view

@external
def bar(arg1: address) -> address:
    return staticcall Foo(arg1).foo()
"""

    c2 = get_contract(contract_2)
    with tx_failed():
        c2.bar(c.address)


@pytest.mark.parametrize("a", ["uint8", "int128", "uint256", "int256"])
@pytest.mark.parametrize("b", ["uint8", "int128", "uint256", "int256"])
def test_tuple_with_address(get_contract, a, b):
    contract_1 = f"""
@external
def foo() -> ({a}, Bytes[3], {b}):
    return 16, b'dog', 1
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> (address, Bytes[3], address): view

@external
def bar(arg1: address) -> (address, Bytes[3], address):
    a: address = empty(address)
    b: Bytes[3] = b""
    c: address = empty(address)
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [16, b"dog", 1]
    assert c2.bar(c.address) == [
        "0x0000000000000000000000000000000000000010",
        b"dog",
        "0x0000000000000000000000000000000000000001",
    ]


@pytest.mark.parametrize("a", ["uint256", "int256"])
@pytest.mark.parametrize("b", ["uint256", "int256"])
def test_tuple_with_address_two(get_contract, a, b):
    contract_1 = f"""
@external
def foo() -> ({a}, Bytes[3], {b}):
    return (2**160)-1, b'dog', (2**160)-2
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> (address, Bytes[3], address): view

@external
def bar(arg1: address) -> (address, Bytes[3], address):
    a: address = empty(address)
    b: Bytes[3] = b""
    c: address = empty(address)
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [(2**160) - 1, b"dog", (2**160) - 2]
    result = c2.bar(c.address)
    assert len(result) == 3
    assert result[0].lower() == "0xffffffffffffffffffffffffffffffffffffffff"
    assert result[1] == b"dog"
    assert result[2].lower() == "0xfffffffffffffffffffffffffffffffffffffffe"


@pytest.mark.parametrize("a", ["uint256", "int256"])
@pytest.mark.parametrize("b", ["uint256", "int256"])
def test_tuple_with_address_too_long(get_contract, tx_failed, a, b):
    contract_1 = f"""
@external
def foo() -> ({a}, Bytes[3], {b}):
    return (2**160)-1, b'dog', 2**160
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def foo() -> (address, Bytes[3], address): view

@external
def bar(arg1: address) -> (address, Bytes[3], address):
    a: address = empty(address)
    b: Bytes[3] = b""
    c: address = empty(address)
    a, b, c = staticcall Foo(arg1).foo()
    return a, b, c
"""

    c2 = get_contract(contract_2)
    assert c.foo() == [(2**160) - 1, b"dog", 2**160]
    with tx_failed():
        c2.bar(c.address)


def test_external_contract_call_state_change(get_contract):
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
    extcall Foo(arg1).set_lucky(arg2)
    """
    c2 = get_contract(contract_2)

    assert c.lucky() == 0
    c2.set_lucky(c.address, lucky_number, transact={})
    assert c.lucky() == lucky_number
    print("Successfully executed an external contract call state change")


def test_constant_external_contract_call_cannot_change_state():
    c = """
interface Foo:
    def set_lucky(_lucky: int128) -> int128: nonpayable

@external
@view
def set_lucky_stmt(arg1: address, arg2: int128):
    extcall Foo(arg1).set_lucky(arg2)
    """

    with pytest.raises(StateAccessViolation):
        compile_code(c)

    c2 = """
interface Foo:
    def set_lucky(_lucky: int128) -> int128: nonpayable
@external
@view
def set_lucky_expr(arg1: address, arg2: int128) -> int128:
    return extcall Foo(arg1).set_lucky(arg2)
    """

    with pytest.raises(StateAccessViolation):
        compile_code(c2)


def test_external_contract_can_be_changed_based_on_address(get_contract):
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
    extcall Foo(arg1).set_lucky(arg2)
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

@deploy
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
    return staticcall Foo(arg1).lucky()
    """
    c2 = get_contract(contract_2)

    assert c2.bar(c.address) == lucky_number
    print("Successfully executed an external contract call with public globals")


def test_external_contract_calls_with_multiple_contracts(get_contract):
    contract_1 = """
lucky: public(int128)

@deploy
def __init__(_lucky: int128):
    self.lucky = _lucky
    """

    lucky_number = 7
    c = get_contract(contract_1, *[lucky_number])

    contract_2 = """
interface Foo:
    def lucky() -> int128: view

magic_number: public(int128)

@deploy
def __init__(arg1: address):
    self.magic_number = staticcall Foo(arg1).lucky()
    """

    c2 = get_contract(contract_2, *[c.address])
    contract_3 = """
interface Bar:
    def magic_number() -> int128: view

best_number: public(int128)

@deploy
def __init__(arg1: address):
    self.best_number = staticcall Bar(arg1).magic_number()
    """

    c3 = get_contract(contract_3, *[c2.address])
    assert c3.best_number() == lucky_number
    print("Successfully executed a multiple external contract calls")


def test_external_contract_calls_with_default_value(get_contract):
    contract_1 = """
@external
def foo(arg1: uint256=1) -> uint256:
    return arg1
    """

    contract_2 = """
interface Foo:
    def foo(arg1: uint256=1) -> uint256: nonpayable

@external
def bar(addr: address) -> uint256:
    return extcall Foo(addr).foo()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    assert c1.foo() == 1
    assert c1.foo(2) == 2
    assert c2.bar(c1.address) == 1


def test_external_contract_calls_with_default_value_two(get_contract):
    contract_1 = """
@external
def foo(arg1: uint256, arg2: uint256=1) -> uint256:
    return arg1 + arg2
    """

    contract_2 = """
interface Foo:
    def foo(arg1: uint256, arg2: uint256=1) -> uint256: nonpayable

@external
def bar(addr: address, arg1: uint256) -> uint256:
    return extcall Foo(addr).foo(arg1)
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    assert c1.foo(2) == 3
    assert c1.foo(2, 3) == 5
    assert c2.bar(c1.address, 2) == 3


def test_extcall_stmt_expr(get_contract):
    # test ExtCall in both stmt and expr position
    contract_1 = """
@external
def bar() -> int128:
    return 1
    """

    contract_2 = """
interface Bar:
    def bar() -> int128: nonpayable

@external
def bar() -> int128:
    return 1

@external
def _stmt(x: address):
    extcall Bar(x).bar()

@external
def _expr(x: address) -> int128:
    return extcall Bar(x).bar()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    c2._stmt(c1.address)
    c2._stmt(c2.address)

    assert c2._expr(c1.address) == 1
    assert c2._expr(c2.address) == 1


def test_invalid_nonexistent_contract_call(w3, tx_failed, get_contract):
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
    return staticcall Bar(x).bar()
    """

    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    assert c2.foo(c1.address) == 1
    with tx_failed():
        c2.foo(w3.eth.accounts[0])
    with tx_failed():
        c2.foo(w3.eth.accounts[3])


def test_invalid_contract_reference_declaration(tx_failed, get_contract):
    contract = """
interface Bar:
    get_magic_number: 1

best_number: public(int128)

@deploy
def __init__():
    pass
"""
    with tx_failed(exception=StructureException):
        get_contract(contract)


def test_invalid_contract_reference_call(tx_failed, get_contract):
    contract = """
@external
def bar(arg1: address, arg2: int128) -> int128:
    return Foo(arg1).foo(arg2)
"""
    with pytest.raises(UndeclaredDefinition):
        compile_code(contract)


def test_invalid_contract_reference_return_type(tx_failed, get_contract):
    contract = """
interface Foo:
    def foo(arg2: int128) -> invalid: view

@external
def bar(arg1: address, arg2: int128) -> int128:
    return staticcall Foo(arg1).foo(arg2)
"""
    with pytest.raises(UnknownType):
        compile_code(contract)


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
    return staticcall self.bar_contract.bar()
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
    extcall self.bar_contract.set_lucky(1)

@external
def get_lucky(contract_address: address) -> int128:
    self.bar_contract = Bar(contract_address)
    return staticcall self.bar_contract.get_lucky()
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


def test_complex_external_contract_call_declaration(get_contract_with_gas_estimation):
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
    return staticcall self.bar_contract.get_lucky()
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
    return staticcall self.bar_contract.bar()
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
    return staticcall self.bar_contract.bar()
    """

    with pytest.raises(InvalidType):
        compile_code(contract_1)


def test_invalid_external_contract_call_declaration_2(assert_compile_failed, get_contract):
    contract_1 = """
interface Bar:
    def bar() -> int128: view

bar_contract: Boo

@external
def foo(contract_address: address) -> int128:
    self.bar_contract = Bar(contract_address)
    return staticcall self.bar_contract.bar()
    """

    with pytest.raises(UnknownType):
        get_contract(contract_1)


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
        return extcall self.bar_contract.get_lucky(value=amount_to_send)
    else: # send it all
        return extcall self.bar_contract.get_lucky(value=msg.value)
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
    assert w3.eth.get_balance(c1.address) == 500
    assert w3.eth.get_balance(c2.address) == 0

    # Send subset of amount
    assert c2.get_lucky(250, call={"value": 500}) == 1
    c2.get_lucky(250, transact={"value": 500})

    # Contract 1 received more money.
    assert c1.get_balance() == 750
    assert w3.eth.get_balance(c1.address) == 750
    assert w3.eth.get_balance(c2.address) == 250


def test_external_call_with_gas(tx_failed, get_contract_with_gas_estimation):
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
    return staticcall self.bar_contract.get_lucky(gas=gas_amount)
    """

    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)
    c2.set_contract(c1.address, transact={})

    assert c2.get_lucky(1000) == 656598
    with tx_failed():
        c2.get_lucky(50)  # too little gas.


def test_skip_contract_check(get_contract_with_gas_estimation):
    contract_2 = """
@external
@view
def bar():
    pass
    """
    contract_1 = """
interface Bar:
    def bar() -> uint256: view
    def baz(): nonpayable

@external
def call_bar(addr: address):
    # would fail if returndatasize check were on
    x: uint256 = staticcall Bar(addr).bar(skip_contract_check=True)
@external
def call_baz():
    # some address with no code
    addr: address = 0x1234567890AbcdEF1234567890aBcdef12345678
    # would fail if extcodesize check were on
    extcall Bar(addr).baz(skip_contract_check=True)
    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)
    c1.call_bar(c2.address)
    c1.call_baz()


def test_invalid_keyword_on_call(assert_compile_failed, get_contract_with_gas_estimation):
    contract_1 = """
interface Bar:
    def set_lucky(arg1: int128): nonpayable
    def get_lucky() -> int128: view

bar_contract: Bar

@external
def get_lucky(amount_to_send: int128) -> int128:
    return staticcall self.bar_contract.get_lucky(gass=1)
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
    s: bool = staticcall Bar(a).bar(1, 2)
    """,
    """
# expected args, none given
interface Bar:
    def bar(arg1: int128) -> bool: view

@external
def foo(a: address):
    s: bool = staticcall Bar(a).bar()
    """,
    """
# expected no args, args given
interface Bar:
    def bar() -> bool: view

@external
def foo(a: address):
    a: bool = staticcall Bar(a).bar(1)
    """,
    """
interface Bar:
    def bar(x: uint256, y: uint256) -> uint256: view

@external
def foo(a: address, x: uint256, y: uint256):
    s: uint256 = staticcall Bar(a).bar(x, y=y)
    """,
]


@pytest.mark.parametrize("bad_code", FAILING_CONTRACTS_STRUCTURE_EXCEPTION)
def test_bad_code_struct_exc(assert_compile_failed, get_contract_with_gas_estimation, bad_code):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), ArgumentException)


def test_bad_skip_contract_check(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
# variable value for skip_contract_check
interface Bar:
    def bar(): payable

@external
def foo():
    x: bool = True
    extcall Bar(msg.sender).bar(skip_contract_check=x)
    """
    with pytest.raises(InvalidType):
        compile_code(code)


def test_tuple_return_external_contract_call(get_contract):
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
    b: address = empty(address)
    c: Bytes[10] = b""
    (a, b, c) = staticcall Test(addr).out_literals()
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
    return X(x=1, y=0x0000000000000000000000000000000000012345)
    """

    contract_2 = """
struct X:
    x: int128
    y: address
interface Test:
    def out_literals() -> X : view

@external
def test(addr: address) -> (int128, address):
    ret: X = staticcall Test(addr).out_literals()
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
    return X(x={i}, y="{s}", z=b"{s}")
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
    ret: X = staticcall Test(addr).get_struct_x()
    return ret.x, ret.y, ret.z

    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.get_struct_x() == (i, s, bytes(s, "utf-8"))
    assert c2.test(c1.address) == list(c1.get_struct_x())


def test_struct_return_external_contract_call_3(get_contract_with_gas_estimation):
    contract_1 = """
struct X:
    x: int128
@external
def out_literals() -> X:
    return X(x=1)
    """

    contract_2 = """
struct X:
    x: int128
interface Test:
    def out_literals() -> X : view

@external
def test(addr: address) -> int128:
    ret: X = staticcall Test(addr).out_literals()
    return ret.x

    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.out_literals() == (1,)
    assert [c2.test(c1.address)] == list(c1.out_literals())


def test_constant_struct_return_external_contract_call_1(get_contract_with_gas_estimation):
    contract_1 = """
struct X:
    x: int128
    y: address

BAR: constant(X) = X(x=1, y=0x0000000000000000000000000000000000012345)

@external
def out_literals() -> X:
    return BAR
    """

    contract_2 = """
struct X:
    x: int128
    y: address
interface Test:
    def out_literals() -> X : view

@external
def test(addr: address) -> (int128, address):
    ret: X = staticcall Test(addr).out_literals()
    return ret.x, ret.y

    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.out_literals() == (1, "0x0000000000000000000000000000000000012345")
    assert c2.test(c1.address) == list(c1.out_literals())


@pytest.mark.parametrize("i,ln,s,", [(100, 6, "abcde"), (41, 40, "a" * 34), (57, 70, "z" * 68)])
def test_constant_struct_return_external_contract_call_2(
    get_contract_with_gas_estimation, i, ln, s
):
    contract_1 = f"""
struct X:
    x: int128
    y: String[{ln}]
    z: Bytes[{ln}]

BAR: constant(X) = X(x={i}, y="{s}", z=b"{s}")

@external
def get_struct_x() -> X:
    return BAR
    """

    contract_2 = f"""
struct X:
    x: int128
    y: String[{ln}]
    z: Bytes[{ln}]
interface Test:
    def get_struct_x() -> X: view

@external
def test(addr: address) -> (int128, String[{ln}], Bytes[{ln}]):
    ret: X = staticcall Test(addr).get_struct_x()
    return ret.x, ret.y, ret.z

    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.get_struct_x() == (i, s, bytes(s, "utf-8"))
    assert c2.test(c1.address) == list(c1.get_struct_x())


def test_constant_struct_return_external_contract_call_3(get_contract_with_gas_estimation):
    contract_1 = """
struct X:
    x: int128

BAR: constant(X) = X(x=1)

@external
def out_literals() -> X:
    return BAR
    """

    contract_2 = """
struct X:
    x: int128
interface Test:
    def out_literals() -> X: view

@external
def test(addr: address) -> int128:
    ret: X = staticcall Test(addr).out_literals()
    return ret.x

    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.out_literals() == (1,)
    assert [c2.test(c1.address)] == list(c1.out_literals())


def test_constant_struct_member_return_external_contract_call_1(get_contract_with_gas_estimation):
    contract_1 = """
struct X:
    x: int128
    y: address

BAR: constant(X) = X(x=1, y=0x0000000000000000000000000000000000012345)

@external
def get_y() -> address:
    return BAR.y
    """

    contract_2 = """
interface Test:
    def get_y() -> address: view

@external
def test(addr: address) -> address:
    ret: address = staticcall Test(addr).get_y()
    return ret
    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.get_y() == "0x0000000000000000000000000000000000012345"
    assert c2.test(c1.address) == "0x0000000000000000000000000000000000012345"


@pytest.mark.parametrize("i,ln,s,", [(100, 6, "abcde"), (41, 40, "a" * 34), (57, 70, "z" * 68)])
def test_constant_struct_member_return_external_contract_call_2(
    get_contract_with_gas_estimation, i, ln, s
):
    contract_1 = f"""
struct X:
    x: int128
    y: String[{ln}]
    z: Bytes[{ln}]

BAR: constant(X) = X(x={i}, y="{s}", z=b"{s}")

@external
def get_y() -> String[{ln}]:
    return BAR.y
    """

    contract_2 = f"""
interface Test:
    def get_y() -> String[{ln}] : view

@external
def test(addr: address) -> String[{ln}]:
    ret: String[{ln}] = staticcall Test(addr).get_y()
    return ret

    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.get_y() == s
    assert c2.test(c1.address) == s


def test_constant_struct_member_return_external_contract_call_3(get_contract_with_gas_estimation):
    contract_1 = """
struct X:
    x: int128

BAR: constant(X) = X(x=1)

@external
def get_x() -> int128:
    return BAR.x
    """

    contract_2 = """
interface Test:
    def get_x() -> int128: view

@external
def test(addr: address) -> int128:
    ret: int128 = staticcall Test(addr).get_x()
    return ret

    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.get_x() == 1
    assert c2.test(c1.address) == 1


def test_constant_nested_struct_return_external_contract_call_1(get_contract_with_gas_estimation):
    contract_1 = """
struct X:
    x: int128
    y: address

struct A:
    a: X
    b: uint256

BAR: constant(A) = A(a=X(x=1, y=0x0000000000000000000000000000000000012345), b=777)

@external
def out_literals() -> A:
    return BAR
    """

    contract_2 = """
struct X:
    x: int128
    y: address

struct A:
    a: X
    b: uint256

interface Test:
    def out_literals() -> A: view

@external
def test(addr: address) -> (X, uint256):
    ret: A = staticcall Test(addr).out_literals()
    return ret.a, ret.b
    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.out_literals() == ((1, "0x0000000000000000000000000000000000012345"), 777)
    assert c2.test(c1.address) == list(c1.out_literals())


@pytest.mark.parametrize("i,ln,s,", [(100, 6, "abcde"), (41, 40, "a" * 34), (57, 70, "z" * 68)])
def test_constant_nested_struct_return_external_contract_call_2(
    get_contract_with_gas_estimation, i, ln, s
):
    contract_1 = f"""
struct X:
    x: int128
    y: String[{ln}]
    z: Bytes[{ln}]

struct A:
    a: X
    b: uint256

BAR: constant(A) = A(a=X(x={i}, y="{s}", z=b"{s}"), b=777)

@external
def get_struct_a() -> A:
    return BAR
    """

    contract_2 = f"""
struct X:
    x: int128
    y: String[{ln}]
    z: Bytes[{ln}]

struct A:
    a: X
    b: uint256

interface Test:
    def get_struct_a() -> A: view

@external
def test(addr: address) -> (X, uint256):
    ret: A = staticcall Test(addr).get_struct_a()
    return ret.a, ret.b

    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.get_struct_a() == ((i, s, bytes(s, "utf-8")), 777)
    assert c2.test(c1.address) == list(c1.get_struct_a())


def test_constant_nested_struct_return_external_contract_call_3(get_contract_with_gas_estimation):
    contract_1 = """
struct X:
    x: int128
    y: int128

struct A:
    a: X
    b: uint256

struct C:
    c: A
    d: bool

BAR: constant(C) = C(c=A(a=X(x=1, y=-1), b=777), d=True)

@external
def out_literals() -> C:
    return BAR
    """

    contract_2 = """
struct X:
    x: int128
    y: int128

struct A:
    a: X
    b: uint256

struct C:
    c: A
    d: bool

interface Test:
    def out_literals() -> C : view

@external
def test(addr: address) -> (A, bool):
    ret: C = staticcall Test(addr).out_literals()
    return ret.c, ret.d
    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.out_literals() == (((1, -1), 777), True)
    assert c2.test(c1.address) == list(c1.out_literals())


def test_constant_nested_struct_member_return_external_contract_call_1(
    get_contract_with_gas_estimation,
):
    contract_1 = """
struct X:
    x: int128
    y: address

struct A:
    a: X
    b: uint256

BAR: constant(A) = A(a=X(x=1, y=0x0000000000000000000000000000000000012345), b=777)

@external
def get_y() -> address:
    return BAR.a.y
    """

    contract_2 = """
interface Test:
    def get_y() -> address: view

@external
def test(addr: address) -> address:
    ret: address = staticcall Test(addr).get_y()
    return ret
    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.get_y() == "0x0000000000000000000000000000000000012345"
    assert c2.test(c1.address) == "0x0000000000000000000000000000000000012345"


@pytest.mark.parametrize("i,ln,s,", [(100, 6, "abcde"), (41, 40, "a" * 34), (57, 70, "z" * 68)])
def test_constant_nested_struct_member_return_external_contract_call_2(
    get_contract_with_gas_estimation, i, ln, s
):
    contract_1 = f"""
struct X:
    x: int128
    y: String[{ln}]
    z: Bytes[{ln}]

struct A:
    a: X
    b: uint256
    c: bool

BAR: constant(A) = A(a=X(x={i}, y="{s}", z=b"{s}"), b=777, c=True)

@external
def get_y() -> String[{ln}]:
    return BAR.a.y
    """

    contract_2 = f"""
interface Test:
    def get_y() -> String[{ln}]: view

@external
def test(addr: address) -> String[{ln}]:
    ret: String[{ln}] = staticcall Test(addr).get_y()
    return ret

    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.get_y() == s
    assert c2.test(c1.address) == s


def test_constant_nested_struct_member_return_external_contract_call_3(
    get_contract_with_gas_estimation,
):
    contract_1 = """
struct X:
    x: int128
    y: int128

struct A:
    a: X
    b: uint256

struct C:
    c: A
    d: bool

BAR: constant(C) = C(c=A(a=X(x=1, y=-1), b=777), d=True)

@external
def get_y() -> int128:
    return BAR.c.a.y

@external
def get_b() -> uint256:
    return BAR.c.b
    """

    contract_2 = """
interface Test:
    def get_y() -> int128: view
    def get_b() -> uint256: view

@external
def test(addr: address) -> int128:
    ret: int128 = staticcall Test(addr).get_y()
    return ret

@external
def test2(addr: address) -> uint256:
    ret: uint256 = staticcall Test(addr).get_b()
    return ret
    """
    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.get_y() == -1
    assert c2.test(c1.address) == -1

    assert c1.get_b() == 777
    assert c2.test2(c1.address) == 777


def test_dynamically_sized_struct_external_contract_call(get_contract_with_gas_estimation):
    contract_1 = """
struct X:
    x: uint256
    y: Bytes[6]

@external
def foo(x: X) -> Bytes[6]:
    return x.y
    """

    contract_2 = """
struct X:
    x: uint256
    y: Bytes[6]

interface Foo:
    def foo(x: X) -> Bytes[6]: nonpayable

@external
def bar(addr: address) -> Bytes[6]:
    _X: X = X(x=1, y=b"hello")
    return extcall Foo(addr).foo(_X)
    """

    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.foo((1, b"hello")) == b"hello"
    assert c2.bar(c1.address) == b"hello"


def test_dynamically_sized_struct_external_contract_call_2(get_contract_with_gas_estimation):
    contract_1 = """
struct X:
    x: uint256
    y: String[6]

@external
def foo(x: X) -> String[6]:
    return x.y
    """

    contract_2 = """
struct X:
    x: uint256
    y: String[6]

interface Foo:
    def foo(x: X) -> String[6]: nonpayable

@external
def bar(addr: address) -> String[6]:
    _X: X = X(x=1, y="hello")
    return extcall Foo(addr).foo(_X)
    """

    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.foo((1, "hello")) == "hello"
    assert c2.bar(c1.address) == "hello"


def test_dynamically_sized_struct_member_external_contract_call(get_contract_with_gas_estimation):
    contract_1 = """
@external
def foo(b: Bytes[6]) -> Bytes[6]:
    return b
    """

    contract_2 = """
struct X:
    x: uint256
    y: Bytes[6]

interface Foo:
    def foo(b: Bytes[6]) -> Bytes[6]: nonpayable

@external
def bar(addr: address) -> Bytes[6]:
    _X: X = X(x=1, y=b"hello")
    return extcall Foo(addr).foo(_X.y)
    """

    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.foo(b"hello") == b"hello"
    assert c2.bar(c1.address) == b"hello"


def test_dynamically_sized_struct_member_external_contract_call_2(get_contract_with_gas_estimation):
    contract_1 = """
@external
def foo(s: String[6]) -> String[6]:
    return s
    """

    contract_2 = """
struct X:
    x: uint256
    y: String[6]

interface Foo:
    def foo(b: String[6]) -> String[6]: nonpayable

@external
def bar(addr: address) -> String[6]:
    _X: X = X(x=1, y="hello")
    return extcall Foo(addr).foo(_X.y)
    """

    c1 = get_contract_with_gas_estimation(contract_1)
    c2 = get_contract_with_gas_estimation(contract_2)

    assert c1.foo("hello") == "hello"
    assert c2.bar(c1.address) == "hello"


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
    return staticcall Foo(arg1).array()
    """

    c2 = get_contract(contract_2)
    assert c2.get_array(c.address) == [0, 0, 0]


def test_returndatasize_too_short(get_contract, tx_failed):
    contract_1 = """
@external
def bar(a: int128) -> int128:
    return a
    """
    contract_2 = """
interface Bar:
    def bar(a: int128) -> (int128, int128): view

@external
def foo(_addr: address) -> (int128, int128):
    return staticcall Bar(_addr).bar(456)
    """
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    with tx_failed():
        c2.foo(c1.address)


def test_returndatasize_empty(get_contract, tx_failed):
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
    return staticcall Bar(_addr).bar(456)
"""
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)
    with tx_failed():
        c2.foo(c1.address)


def test_returndatasize_too_long(get_contract):
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
    return staticcall Bar(_addr).bar(456)
"""
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    # excess return data does not raise
    assert c2.foo(c1.address) == 456


def test_no_returndata(get_contract, tx_failed):
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
    x: int128 = staticcall Bar(_addr).bar(456)
    # make two calls to confirm EVM behavior: RETURNDATA is always based on the last call
    y: int128 = staticcall Bar(_addr2).bar(123)
    return y

"""
    c1 = get_contract(contract_1)
    c2 = get_contract(contract_2)

    assert c2.foo(c1.address, c1.address) == 123
    with tx_failed():
        c2.foo(c1.address, "0x1234567890123456789012345678901234567890")


def test_default_override(get_contract, tx_failed):
    bad_erc20_code = """
@external
def transfer(receiver: address, amount: uint256):
    pass
    """

    negative_transfer_code = """
@external
def transfer(receiver: address, amount: uint256) -> bool:
    return False
    """

    self_destructing_code = """
@external
def transfer(receiver: address, amount: uint256):
    selfdestruct(msg.sender)
    """

    code = """
from ethereum.ercs import IERC20
@external
def safeTransfer(erc20: IERC20, receiver: address, amount: uint256) -> uint256:
    assert extcall erc20.transfer(receiver, amount, default_return_value=True)
    return 7

@external
def transferBorked(erc20: IERC20, receiver: address, amount: uint256):
    assert extcall erc20.transfer(receiver, amount)
    """
    bad_erc20 = get_contract(bad_erc20_code)
    c = get_contract(code)

    # demonstrate transfer failing
    with tx_failed():
        c.transferBorked(bad_erc20.address, c.address, 0)
    # would fail without default_return_value
    assert c.safeTransfer(bad_erc20.address, c.address, 0) == 7

    # check that `default_return_value` does not stomp valid returndata.
    negative_contract = get_contract(negative_transfer_code)
    with tx_failed():
        c.safeTransfer(negative_contract.address, c.address, 0)

    # default_return_value should fail on EOAs (addresses with no code)
    random_address = "0x0000000000000000000000000000000000001234"
    with tx_failed():
        c.safeTransfer(random_address, c.address, 1)

    # in this case, the extcodesize check runs after the token contract
    # selfdestructs. however, extcodesize still returns nonzero until
    # later (i.e., after this transaction), so we still pass
    # the extcodesize check.
    self_destructing_contract = get_contract(self_destructing_code)
    assert c.safeTransfer(self_destructing_contract.address, c.address, 0) == 7


def test_default_override2(get_contract, tx_failed):
    bad_code_1 = """
@external
def return_64_bytes() -> bool:
    return True
    """

    bad_code_2 = """
@external
def return_64_bytes():
    pass
    """

    code = """
struct BoolPair:
    x: bool
    y: bool
interface Foo:
    def return_64_bytes() -> BoolPair: nonpayable
@external
def bar(foo: Foo):
    t: BoolPair = extcall foo.return_64_bytes(default_return_value=BoolPair(x=True, y=True))
    assert t.x and t.y
    """
    bad_1 = get_contract(bad_code_1)
    bad_2 = get_contract(bad_code_2)
    c = get_contract(code)

    # fails due to returndatasize being nonzero but also lt 64
    with tx_failed():
        c.bar(bad_1.address)
    c.bar(bad_2.address)


def test_contract_address_evaluation(get_contract):
    callee_code = """
# implements: Foo

interface Counter:
    def increment_counter(): nonpayable

@external
def foo():
    pass

@external
def bar() -> address:
    extcall Counter(msg.sender).increment_counter()
    return self
    """
    code = """
# implements: Counter

interface Foo:
    def foo(): nonpayable
    def bar() -> address: nonpayable

counter: uint256

@external
def increment_counter():
    self.counter += 1

@external
def do_stuff(f: Foo) -> uint256:
    extcall Foo(extcall f.bar()).foo()
    return self.counter
    """

    c1 = get_contract(code)
    c2 = get_contract(callee_code)

    assert c1.do_stuff(c2.address) == 1


TEST_ADDR = b"".join(chr(i).encode("utf-8") for i in range(20)).hex()


@pytest.mark.parametrize("typ,val", [("address", TEST_ADDR)])
def test_calldata_clamp(w3, get_contract, tx_failed, keccak, typ, val):
    code = f"""
@external
def foo(a: {typ}):
    pass
    """
    c1 = get_contract(code)
    sig = keccak(f"foo({typ})".encode()).hex()[:10]
    encoded = abi.encode(f"({typ})", (val,)).hex()
    data = f"{sig}{encoded}"

    # Static size is short by 1 byte
    malformed = data[:-2]
    with tx_failed():
        w3.eth.send_transaction({"to": c1.address, "data": malformed})

    # Static size is exact
    w3.eth.send_transaction({"to": c1.address, "data": data})

    # Static size exceeds by 1 byte, ok
    w3.eth.send_transaction({"to": c1.address, "data": data + "ff"})


@pytest.mark.parametrize("typ,val", [("address", ([TEST_ADDR] * 3, "vyper"))])
def test_dynamic_calldata_clamp(w3, get_contract, tx_failed, keccak, typ, val):
    code = f"""
@external
def foo(a: DynArray[{typ}, 3], b: String[5]):
    pass
    """

    c1 = get_contract(code)
    sig = keccak(f"foo({typ}[],string)".encode()).hex()[:10]
    encoded = abi.encode(f"({typ}[],string)", val).hex()
    data = f"{sig}{encoded}"

    # Dynamic size is short by 1 byte
    malformed = data[:264]
    with tx_failed():
        w3.eth.send_transaction({"to": c1.address, "data": malformed})

    # Dynamic size is at least minimum (132 bytes * 2 + 2 (for 0x) = 266)
    valid = data[:266]
    w3.eth.send_transaction({"to": c1.address, "data": valid})
