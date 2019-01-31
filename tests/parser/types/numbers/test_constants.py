from decimal import Decimal
from vyper.compiler import compile_code


def test_builtin_constants(get_contract_with_gas_estimation):
    code = """
@public
def test_zaddress(a: address) -> bool:
    return a == ZERO_ADDRESS


@public
def test_empty_bytes32(a: bytes32) -> bool:
    return a == EMPTY_BYTES32


@public
def test_int128(a: int128) -> (bool, bool):
    return a == MAX_INT128, a == MIN_INT128


@public
def test_decimal(a: decimal) -> (bool, bool):
    return a == MAX_DECIMAL, a == MIN_DECIMAL


@public
def test_uint256(a: uint256) -> bool:
    return a == MAX_UINT256


@public
def test_arithmetic(a: int128) -> int128:
    return MAX_INT128 - a
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test_empty_bytes32(b"\x00" * 32) is True
    assert c.test_empty_bytes32(b"\x0F" * 32) is False

    assert c.test_zaddress("0x0000000000000000000000000000000000000000") is True
    assert c.test_zaddress("0x0000000000000000000000000000000000000012") is False

    assert c.test_int128(2**127 - 1) == [True, False]
    assert c.test_int128(-2**127) == [False, True]
    assert c.test_int128(0) == [False, False]

    assert c.test_decimal(Decimal(2**127 - 1)) == [True, False]
    assert c.test_decimal(Decimal('-170141183460469231731687303715884105728')) == [False, True]
    assert c.test_decimal(Decimal('0.1')) == [False, False]

    assert c.test_uint256(2**256 - 1) is True

    assert c.test_arithmetic(5000) == 2**127 - 1 - 5000


def test_builtin_constants_assignment(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> int128:
    bar: int128 = MAX_INT128
    return bar

@public
def goo() -> int128:
    bar: int128 = MIN_INT128
    return bar

@public
def hoo() -> bytes32:
    bar: bytes32 = EMPTY_BYTES32
    return bar

@public
def joo() -> address:
    bar: address = ZERO_ADDRESS
    return bar

@public
def koo() -> decimal:
    bar: decimal = MAX_DECIMAL
    return bar

@public
def loo() -> decimal:
    bar: decimal = MIN_DECIMAL
    return bar

@public
def zoo() -> uint256:
    bar: uint256 = MAX_UINT256
    return bar
    """

    c = get_contract_with_gas_estimation(code)

    assert c.foo() == 2**127 - 1
    assert c.goo() == -2**127

    assert c.hoo() == b"\x00" * 32

    assert c.joo() is None

    assert c.koo() == Decimal(2**127 - 1)
    assert c.loo() == Decimal(-2**127)

    assert c.zoo() == 2**256 - 1


def test_reserved_keyword(get_contract, assert_compile_failed):
    code = """
@public
def test():
    ZERO_ADDRESS: address
    """
    assert_compile_failed(lambda: get_contract(code))


def test_custom_constants(get_contract):
    code = """
X_VALUE: constant(uint256) = 33

@public
def test() -> uint256:
    return X_VALUE

@public
def test_add(a: uint256) -> uint256:
    return X_VALUE + a
    """
    c = get_contract(code)

    assert c.test() == 33
    assert c.test_add(7) == 40


def test_constant_address(get_contract):
    code = """
OWNER: constant(address) = 0x0000000000000000000000000000000000000012

@public
def get_owner() -> address:
    return OWNER

@public
def is_owner() -> bool:
    if msg.sender == OWNER:
        return True
    else:
        return False
    """
    c = get_contract(code)

    assert c.get_owner() == '0x0000000000000000000000000000000000000012'
    assert c.is_owner() is False


def test_constant_bytes(get_contract):
    test_str = b"Alabama, Arkansas. I do love my ma and pa"
    code = """
X: constant(bytes[100]) = b"{}"

@public
def test() -> bytes[100]:
    y: bytes[100] = X

    return y
    """.format(test_str.decode())

    c = get_contract(code)

    assert c.test() == test_str


def test_constant_custom_units(get_contract):
    code = """
units: {
    share: "Share unit"
}


MAX_SHARES: constant(uint256(share)) = 1000
SHARE_PRICE: constant(uint256(wei/share)) = 5


@public
def market_cap() -> uint256(wei):
    return MAX_SHARES * SHARE_PRICE
    """

    c = get_contract(code)

    assert c.market_cap() == 5000


def test_constant_folds(search_for_sublist):
    code = """
SOME_CONSTANT: constant(uint256) = 11 + 1


@public
def test(some_dynamic_var: uint256) -> uint256:
    return some_dynamic_var  +  2**SOME_CONSTANT
    """

    lll = compile_code(code, ['ir'])['ir']
    assert search_for_sublist(lll, ['add', ['mload', [320]], [4096]])
