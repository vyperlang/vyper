from vyper.exceptions import (
    InvalidLiteralException
)


def test_convert_bytes_to_int128(assert_compile_failed, get_contract_with_gas_estimation):
    # Test valid bytes input for conversion
    test_success = """
@public
def foo(bar: bytes[5]) -> int128:
    return convert(bar, int128)
    """

    c = get_contract_with_gas_estimation(test_success)
    assert c.foo(b'\x00\x00\x00\x00\x00') == 0
    assert c.foo(b'\x00\x07\x5B\xCD\x15') == 123456789

    test_success = """
@public
def foo(bar: bytes[32]) -> int128:
    return convert(bar, int128)
    """

    c = get_contract_with_gas_estimation(test_success)
    assert c.foo(b'\x00' * 32) == 0
    assert c.foo(b'\xff' * 32) == -1

    # Test overflow bytes input for conversion
    test_fail = """
@public
def foo(bar: bytes[33]) -> int128:
    return convert(bar, int128)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(test_fail),
        InvalidLiteralException
    )

    test_fail = """
@public
def foobar() -> int128:
    barfoo: bytes[63] = "Hello darkness, my old friend I've come to talk with you again."
    return convert(barfoo, int128)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(test_fail),
        InvalidLiteralException
    )


def test_convert_from_bool(get_contract_with_gas_estimation):
    code = """
@public
def from_bool(flag: bool) -> int128:
    flagInt: int128 = convert(flag, int128)
    return flagInt
    """

    c = get_contract_with_gas_estimation(code)
    assert c.from_bool(False) == 0
    assert c.from_bool(True) == 1


def test_convert_bytes32_to_num_overflow(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def test1():
    y: bytes32 = 0x1000000000000000000000000000000000000000000000000000000000000000
    x: int128 = convert(y, int128)
    """

    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.test1())


def test_convert_address_to_num(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def test2():
    x: int128 = convert(msg.sender, int128)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)


def test_convert_out_of_range(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def test2():
    x: int128
    x = convert(340282366920938463463374607431768211459, int128)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)
