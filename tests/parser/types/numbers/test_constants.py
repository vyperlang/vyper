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
