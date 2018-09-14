from decimal import Decimal


def test_builtin_constants(get_contract_with_gas_estimation):
    code = """
@public
def test_zaddress(a: address) -> bool:
    return a == ZERO_ADDRESS


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
