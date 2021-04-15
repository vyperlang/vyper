from decimal import Decimal

from vyper.exceptions import InvalidLiteral, TypeMismatch


def test_convert_from_int128(get_contract_with_gas_estimation):
    code = """
a: int128
b: decimal

@external
def int128_to_decimal(inp: int128) -> (decimal, decimal, decimal):
    self.a = inp
    memory: decimal = convert(inp, decimal)
    storage: decimal = convert(self.a, decimal)
    literal: decimal = convert(1, decimal)
    return  memory, storage, literal
"""
    c = get_contract_with_gas_estimation(code)
    assert c.int128_to_decimal(1) == [1.0, 1.0, 1.0]


def test_convert_from_uint256(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@external
def test_variable() -> bool:
    a: uint256 = 1000
    return convert(a, decimal) == 1000.0

@external
def test_passed_variable(a: uint256) -> decimal:
    return convert(a, decimal)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test_variable() is True
    assert c.test_passed_variable(256) == 256
    max_decimal = 2 ** 127 - 1
    assert c.test_passed_variable(max_decimal) == Decimal(max_decimal)
    assert_tx_failed(lambda: c.test_passed_variable(max_decimal + 1))


def test_convert_from_uint256_overflow(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@external
def foo() -> decimal:
    return convert(2**127, decimal)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), InvalidLiteral)


def test_convert_from_bool(get_contract_with_gas_estimation):
    code = """
@external
def foo(bar: bool) -> decimal:
    return convert(bar, decimal)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo(False) == 0.0
    assert c.foo(True) == 1.0


def test_convert_from_bytes32(get_contract_with_gas_estimation):
    code = """
@external
def foo(bar: bytes32) -> decimal:
    return convert(bar, decimal)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo(b"\x00" * 32) == 0.0
    assert c.foo(b"\xff" * 32) == -1.0
    assert c.foo((b"\x00" * 31) + b"\x01") == 1.0
    assert c.foo((b"\x00" * 30) + b"\x01\x00") == 256.0


def test_convert_from_bytes32_overflow(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@external
def foo() -> decimal:
    return convert(0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF, decimal)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), InvalidLiteral)


def test_convert_from_bytes(get_contract_with_gas_estimation):
    code = """
@external
def foo(bar: Bytes[5]) -> decimal:
    return convert(bar, decimal)

@external
def goo(bar: Bytes[32]) -> decimal:
    return convert(bar, decimal)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.foo(b"\x00\x00\x00\x00\x00") == 0.0
    assert c.foo(b"\x00\x07\x5B\xCD\x15") == 123456789.0

    assert c.goo(b"") == 0.0
    assert c.goo(b"\x00") == 0.0
    assert c.goo(b"\x01") == 1.0
    assert c.goo(b"\x00\x01") == 1.0
    assert c.goo(b"\x01\x00") == 256.0
    assert c.goo(b"\x01\x00\x00\x00\x01") == 4294967297.0
    assert c.goo(b"\xff" * 32) == -1.0


def test_convert_from_too_many_bytes(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@external
def foo(bar: Bytes[33]) -> decimal:
    return convert(bar, decimal)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code), TypeMismatch,
    )

    code = """
@external
def foobar() -> decimal:
    barfoo: Bytes[63] = b"Hello darkness, my old friend I've come to talk with you again."
    return convert(barfoo, decimal)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code), TypeMismatch,
    )


def test_convert_from_address(get_contract_with_gas_estimation):
    code = """
stor: address

@external
def conv(param: address) -> decimal:
    return convert(param, decimal)

@external
def conv_zero_literal() -> decimal:
    return convert(ZERO_ADDRESS, decimal)

@external
def conv_zero_stor() -> decimal:
    self.stor = ZERO_ADDRESS
    return convert(self.stor, decimal)

@external
def conv_neg1_literal() -> decimal:
    return convert(0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF, decimal)

@external
def conv_neg1_stor() -> decimal:
    self.stor = 0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF
    return convert(self.stor, decimal)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.conv(b"\x00" * 20) == 0.0
    assert c.conv_zero_literal() == 0.0
    assert c.conv_zero_stor() == 0.0

    assert c.conv(b"\xff" * 20) == -1.0
    assert c.conv_neg1_literal() == -1.0
    assert c.conv_neg1_stor() == -1.0

    assert c.conv((b"\x00" * 19) + b"\x01") == 1.0
    assert c.conv((b"\x00" * 18) + b"\x01\x00") == 256.0


def test_convert_from_int256(get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@external
def test(foo: int256) -> decimal:
    return convert(foo, decimal)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.test(0) == 0
    assert c.test(-1) == -1
    assert c.test(2 ** 127 - 1) == 2 ** 127 - 1
    assert c.test(-(2 ** 127)) == -(2 ** 127)
    assert_tx_failed(lambda: c.test(2 ** 127))
    assert_tx_failed(lambda: c.test(2 ** 255 - 1))
    assert_tx_failed(lambda: c.test(-(2 ** 127) - 1))
    assert_tx_failed(lambda: c.test(-(2 ** 255)))
