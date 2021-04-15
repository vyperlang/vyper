from vyper.exceptions import InvalidLiteral, OverflowException, TypeMismatch
from vyper.utils import SizeLimits


def test_convert_to_int128(get_contract_with_gas_estimation):
    code = """
a: uint256
b: bytes32
c: Bytes[1]

@external
def uint256_to_num(inp: uint256) -> (int128, int128):
    self.a = inp
    memory: int128  = convert(inp, int128)
    storage: int128 = convert(self.a, int128)
    return  memory, storage

@external
def bytes32_to_num() -> (int128, int128):
    self.b = 0x0000000000000000000000000000000000000000000000000000000000000001
    literal: int128 = convert(0x0000000000000000000000000000000000000000000000000000000000000001, int128)  # noqa: E501
    storage: int128 = convert(self.b, int128)
    return literal, storage

@external
def bytes_to_num() -> (int128, int128):
    self.c = b'a'
    literal: int128 = convert('a', int128)
    storage: int128 = convert(self.c, int128)
    return literal, storage

@external
def zero_bytes(inp: Bytes[1]) -> int128:
    return convert(inp, int128)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.uint256_to_num(1) == [1, 1]
    assert c.bytes32_to_num() == [1, 1]
    assert c.bytes_to_num() == [97, 97]

    assert c.zero_bytes(b"\x01") == 1
    assert c.zero_bytes(b"\x00") == 0


def test_convert_from_bytes(
    assert_compile_failed, assert_tx_failed, get_contract_with_gas_estimation
):
    # Test valid bytes input for conversion
    test_success = """
@external
def foo(bar: Bytes[5]) -> int128:
    return convert(bar, int128)
    """

    c = get_contract_with_gas_estimation(test_success)
    assert c.foo(b"\x00\x00\x00\x00\x00") == 0
    assert c.foo(b"\x00\x07\x5B\xCD\x15") == 123456789

    test_success = """
@external
def foo(bar: Bytes[32]) -> int128:
    return convert(bar, int128)
    """

    c = get_contract_with_gas_estimation(test_success)
    assert c.foo(b"") == 0
    assert c.foo(b"\x00") == 0
    assert c.foo(b"\x01") == 1
    assert c.foo(b"\x00\x01") == 1
    assert c.foo(b"\x01\x00") == 256
    assert c.foo(b"\x01\x00\x00\x00\x01") == 4294967297
    assert c.foo(b"\xff" * 32) == -1
    assert_tx_failed(lambda: c.foo(b"\x80" + b"\xff" * 31))
    assert_tx_failed(lambda: c.foo(b"\x01" * 33))

    bytes_to_num_code = """
astor: Bytes[10]

@external
def bar_storage() -> int128:
    self.astor = b"a"
    return convert(self.astor, int128)
    """

    c = get_contract_with_gas_estimation(bytes_to_num_code)
    assert c.bar_storage() == 97

    # Test overflow bytes input for conversion
    test_fail = """
@external
def foo(bar: Bytes[33]) -> int128:
    return convert(bar, int128)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(test_fail), TypeMismatch)

    test_fail = """
@external
def foobar() -> int128:
    barfoo: Bytes[63] = b"Hello darkness, my old friend I've come to talk with you again."
    return convert(barfoo, int128)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(test_fail), TypeMismatch,
    )


def test_convert_from_bool(get_contract_with_gas_estimation):
    code = """
@external
def from_bool(flag: bool) -> int128:
    flagInt: int128 = convert(flag, int128)
    return flagInt
    """

    c = get_contract_with_gas_estimation(code)
    assert c.from_bool(False) == 0
    assert c.from_bool(True) == 1


def test_convert_from_uint256(get_contract_with_gas_estimation):
    code = """
@external
def test(foo: uint256) -> int128:
    return convert(foo, int128)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.test(0) == 0
    assert c.test(2 ** 127 - 1) == 2 ** 127 - 1


def test_out_of_range_from_uint256(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@external
def test(foo: uint256) -> int128:
    return convert(foo, int128)
    """

    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.test(2 ** 127))
    assert_tx_failed(lambda: c.test(2 ** 256 - 1))


def test_out_of_range_from_uint256_at_compile(
    assert_compile_failed, get_contract_with_gas_estimation
):
    code = """
@external
def test() -> int128:
    return convert(2**127, int128)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), InvalidLiteral)

    code = """
@external
def test() -> int128:
    return convert(2**127, int128)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), InvalidLiteral)


def test_convert_from_bytes32_overflow(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@external
def test1():
    y: bytes32 = 0x1000000000000000000000000000000000000000000000000000000000000000
    x: int128 = convert(y, int128)
    """

    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.test1())


def test_convert_out_of_range_literal(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@external
def test2():
    x: int128
    x = convert(340282366920938463463374607431768211459, int128)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)


def test_convert_from_decimal(get_contract_with_gas_estimation):
    code = """
bar: decimal
nar: decimal
mar: decimal

@external
def foo() -> int128:
    return convert(27.2319, int128)

@external
def hoo() -> int128:
    return convert(-432.298391, int128)

@external
def goo() -> int128:
    return convert(0.1234, int128)

@external
def foobar() -> int128:
    self.bar = 27.2319
    return convert(self.bar, int128)

@external
def hoonar() -> int128:
    self.nar = -432.298391
    return convert(self.nar, int128)

@external
def goomar() -> int128:
    self.mar = 0.1234
    return convert(self.mar, int128)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 27
    assert c.hoo() == -432
    assert c.goo() == 0
    assert c.foobar() == 27
    assert c.hoonar() == -432
    assert c.goomar() == 0


def test_convert_from_overflow_decimal(
    assert_compile_failed, assert_tx_failed, get_contract_with_gas_estimation
):
    code = """
@external
def foo() -> int128:
    return convert(180141183460469231731687303715884105728.0, int128)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code), OverflowException,
    )

    code = """
@external
def foo() -> int128:
    return convert(-180141183460469231731687303715884105728.0, int128)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code), OverflowException,
    )


def test_convert_from_address(w3, get_contract):
    code = """
stor: address

@external
def testCompiles():
    x: int128 = convert(msg.sender, int128)

@external
def conv_neg1_stor() -> int128:
    self.stor = 0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF
    return convert(self.stor, int128)

@external
def conv_neg1_literal() -> int128:
    return convert(0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF, int128)

@external
def conv_neg1_stor_alt() -> int128:
    self.stor = 0x00000000fFFFffffffFfFfFFffFfFffFFFfFffff
    return convert(self.stor, int128)

@external
def conv_neg1_literal_alt() -> int128:
    return convert(0x00000000fFFFffffffFfFfFFffFfFffFFFfFffff, int128)

@external
def conv_min_stor() -> int128:
    self.stor = 0x0000000080000000000000000000000000000000
    return convert(self.stor, int128)

@external
def conv_min_literal() -> int128:
    return convert(0x0000000080000000000000000000000000000000, int128)

@external
def conv_min_stor_alt() -> int128:
    self.stor = 0x1234567880000000000000000000000000000000
    return convert(self.stor, int128)

@external
def conv_min_literal_alt() -> int128:
    return convert(0x1234567880000000000000000000000000000000, int128)

@external
def conv_zero_stor() -> int128:
    self.stor = ZERO_ADDRESS
    return convert(self.stor, int128)

@external
def conv_zero_literal() -> int128:
    return convert(ZERO_ADDRESS, int128)

@external
def conv_zero_stor_alt() -> int128:
    self.stor = 0xffFFfFFf00000000000000000000000000000000
    return convert(self.stor, int128)

@external
def conv_zero_literal_alt() -> int128:
    return convert(0xffFFfFFf00000000000000000000000000000000, int128)

@external
def conv_max_stor() -> int128:
    self.stor = 0xFffffFff7FFFFFFfFffFffFfFFffFffFFfFfffFF
    return convert(self.stor, int128)

@external
def conv_max_literal() -> int128:
    return convert(0xFffffFff7FFFFFFfFffFffFfFFffFffFFfFfffFF, int128)

@external
def conv_max_stor_alt() -> int128:
    self.stor = 0x000000007FfFFffffFFFFfffffffFffFfFffffFF
    return convert(self.stor, int128)

@external
def conv_max_literal_alt() -> int128:
    return convert(0x000000007FfFFffffFFFFfffffffFffFfFffffFF, int128)
    """

    c = get_contract(code)

    assert c.conv_neg1_stor() == -1
    assert c.conv_neg1_literal() == -1
    assert c.conv_neg1_stor_alt() == -1
    assert c.conv_neg1_literal_alt() == -1

    assert c.conv_min_stor() == SizeLimits.MIN_INT128
    assert c.conv_min_literal() == SizeLimits.MIN_INT128
    assert c.conv_min_stor_alt() == SizeLimits.MIN_INT128
    assert c.conv_min_literal_alt() == SizeLimits.MIN_INT128

    assert c.conv_zero_stor() == 0
    assert c.conv_zero_literal() == 0
    assert c.conv_zero_stor_alt() == 0
    assert c.conv_zero_literal_alt() == 0

    assert c.conv_max_stor() == SizeLimits.MAX_INT128
    assert c.conv_max_literal() == SizeLimits.MAX_INT128
    assert c.conv_max_stor_alt() == SizeLimits.MAX_INT128
    assert c.conv_max_literal_alt() == SizeLimits.MAX_INT128


def test_convert_from_int256(get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@external
def test(foo: int256) -> int128:
    return convert(foo, int128)
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
