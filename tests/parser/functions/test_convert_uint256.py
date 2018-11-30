from vyper.exceptions import (
    InvalidLiteralException
)


def test_convert_bytes_to_uint256(assert_compile_failed, get_contract_with_gas_estimation):
    # Test valid bytes input for conversion
    test_success = """
@public
def foo(bar: bytes[5]) -> uint256:
    return convert(bar, uint256)
    """

    c = get_contract_with_gas_estimation(test_success)
    assert c.foo(b'\x00\x00\x00\x00\x00') == 0
    assert c.foo(b'\x00\x07\x5B\xCD\x15') == 123456789

    test_success = """
@public
def foo(bar: bytes[32]) -> uint256:
    return convert(bar, uint256)
    """

    c = get_contract_with_gas_estimation(test_success)
    assert c.foo(b'\x00' * 32) == 0
    assert c.foo(b'\xff' * 32) == ((2**256) - 1)

    # Test overflow bytes input for conversion
    test_fail = """
@public
def foo(bar: bytes[33]) -> uint256:
    return convert(bar, uint256)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(test_fail),
        InvalidLiteralException
    )

    test_fail = """
@public
def foobar() -> uint256:
    barfoo: bytes[63] = "Hello darkness, my old friend I've come to talk with you again."
    return convert(barfoo, uint256)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(test_fail),
        InvalidLiteralException
    )


def test_convert_from_bool(get_contract_with_gas_estimation):
    code = """
@public
def from_bool(flag: bool) -> uint256:
    flagUInt: uint256 = convert(flag, uint256)
    return flagUInt
    """

    c = get_contract_with_gas_estimation(code)
    assert c.from_bool(False) == 0
    assert c.from_bool(True) == 1


def test_convert_to_uint256_with_negative_num(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo() -> uint256:
    return convert(1-2, uint256)
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)


def test_convert_to_uint256_with_negative_input(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(x: int128) -> uint256:
    return convert(x, uint256)
    """
    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.foo(-1))


def test_convert_to_uint256_with_bytes32(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> uint256:
    return convert(convert(-1, bytes32), uint256)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 2 ** 256 - 1
