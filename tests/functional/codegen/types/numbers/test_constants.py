import itertools
from decimal import Decimal

import pytest

from vyper.compiler import compile_code
from vyper.exceptions import TypeMismatch
from vyper.utils import MemoryPositions


def search_for_sublist(ir, sublist):
    _list = ir.to_list() if hasattr(ir, "to_list") else ir
    if _list == sublist:
        return True
    return isinstance(_list, list) and any(search_for_sublist(i, sublist) for i in _list)


def test_builtin_constants(get_contract_with_gas_estimation):
    code = """
@external
def test_zaddress(a: address) -> bool:
    return a == empty(address)


@external
def test_empty_bytes32(a: bytes32) -> bool:
    return a == empty(bytes32)


@external
def test_int128(a: int128) -> (bool, bool):
    return a == max_value(int128), a == min_value(int128)


@external
def test_decimal(a: decimal) -> (bool, bool):
    return a == max_value(decimal), a == min_value(decimal)


@external
def test_uint256(a: uint256) -> bool:
    return a == max_value(uint256)


@external
def test_arithmetic(a: int128) -> int128:
    return max_value(int128) - a
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test_empty_bytes32(b"\x00" * 32) is True
    assert c.test_empty_bytes32(b"\x0F" * 32) is False

    assert c.test_zaddress("0x0000000000000000000000000000000000000000") is True
    assert c.test_zaddress("0x0000000000000000000000000000000000000012") is False

    assert c.test_int128(2**127 - 1) == [True, False]
    assert c.test_int128(-(2**127)) == [False, True]
    assert c.test_int128(0) == [False, False]

    assert c.test_decimal(Decimal("18707220957835557353007165858768422651595.9365500927")) == [
        True,
        False,
    ]
    assert c.test_decimal(Decimal("-18707220957835557353007165858768422651595.9365500928")) == [
        False,
        True,
    ]
    assert c.test_decimal(Decimal("0.1")) == [False, False]

    assert c.test_uint256(2**256 - 1) is True

    assert c.test_arithmetic(5000) == 2**127 - 1 - 5000


def test_builtin_constants_assignment(get_contract_with_gas_estimation):
    code = """
@external
def foo() -> int128:
    bar: int128 = max_value(int128)
    return bar

@external
def goo() -> int128:
    bar: int128 = min_value(int128)
    return bar

@external
def hoo() -> bytes32:
    bar: bytes32 = empty(bytes32)
    return bar

@external
def joo() -> address:
    bar: address = empty(address)
    return bar

@external
def koo() -> decimal:
    bar: decimal = max_value(decimal)
    return bar

@external
def loo() -> decimal:
    bar: decimal = min_value(decimal)
    return bar

@external
def zoo() -> uint256:
    bar: uint256 = max_value(uint256)
    return bar
    """

    c = get_contract_with_gas_estimation(code)

    assert c.foo() == 2**127 - 1
    assert c.goo() == -(2**127)

    assert c.hoo() == b"\x00" * 32

    assert c.joo() is None

    assert c.koo() == Decimal(2**167 - 1) / 10**10
    assert c.loo() == Decimal(-(2**167)) / 10**10

    assert c.zoo() == 2**256 - 1


def test_custom_constants(get_contract):
    code = """
X_VALUE: constant(uint256) = 33

@external
def test() -> uint256:
    return X_VALUE

@external
def test_add(a: uint256) -> uint256:
    return X_VALUE + a
    """
    c = get_contract(code)

    assert c.test() == 33
    assert c.test_add(7) == 40


# Would be nice to put this somewhere accessible, like in vyper.types or something
integer_types = ["uint8", "int128", "int256", "uint256"]


@pytest.mark.parametrize("storage_type,return_type", itertools.permutations(integer_types, 2))
def test_custom_constants_fail(get_contract, assert_compile_failed, storage_type, return_type):
    code = f"""
MY_CONSTANT: constant({storage_type}) = 1

@external
def foo() -> {return_type}:
    return MY_CONSTANT
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


def test_constant_address(get_contract):
    code = """
OWNER: constant(address) = 0x0000000000000000000000000000000000000012

@external
def get_owner() -> address:
    return OWNER

@external
def is_owner() -> bool:
    if msg.sender == OWNER:
        return True
    else:
        return False
    """
    c = get_contract(code)

    assert c.get_owner() == "0x0000000000000000000000000000000000000012"
    assert c.is_owner() is False


def test_constant_bytes(get_contract):
    test_str = b"Alabama, Arkansas. I do love my ma and pa"
    code = f"""
X: constant(Bytes[100]) = b"{test_str.decode()}"

@external
def test() -> Bytes[100]:
    y: Bytes[100] = X

    return y
    """

    c = get_contract(code)

    assert c.test() == test_str


def test_constant_folds():
    some_prime = 10013677
    code = f"""
SOME_CONSTANT: constant(uint256) = 11 + 1
SOME_PRIME: constant(uint256) = {some_prime}

@external
def test() -> uint256:
    # calculate some constant which is really unlikely to be randomly
    # in bytecode
    ret: uint256 = 2**SOME_CONSTANT * SOME_PRIME
    return ret
    """
    ir = compile_code(code, output_formats=["ir"])["ir"]
    search = ["mstore", [MemoryPositions.RESERVED_MEMORY], [2**12 * some_prime]]
    assert search_for_sublist(ir, search)


def test_constant_lists(get_contract):
    code = """
BYTE32_LIST: constant(bytes32[2]) = [
    0x0000000000000000000000000000000000000000000000000000000000001321,
    0x0000000000000000000000000000000000000000000000000000000000001123
]

SPECIAL: constant(int128[3]) = [33, 44, 55]

@external
def test() -> bytes32:
    a: bytes32[2] = BYTE32_LIST
    return a[1]

@view
@external
def contains(a: int128) -> bool:
    return a in SPECIAL
    """

    c = get_contract(code)

    assert c.test()[-2:] == b"\x11\x23"

    assert c.contains(55) is True
    assert c.contains(44) is True
    assert c.contains(33) is True
    assert c.contains(3) is False
