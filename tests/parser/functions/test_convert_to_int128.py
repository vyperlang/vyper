from vyper.exceptions import (
    InvalidLiteralException,
    TypeMismatchException,
)


def test_convert_to_int128_units(get_contract, assert_tx_failed):
    code = """
units: {
    meter: "Meter"
}

@public
def test() -> uint256(meter):
    b: int128(meter) = 4321
    a: uint256(meter) = convert(b, uint256)
    return a
    """

    c = get_contract(code)
    assert c.test() == 4321


def test_convert_to_int128(get_contract_with_gas_estimation):
    code = """
a: uint256
b: bytes32
c: bytes[1]

@public
def uint256_to_num(inp: uint256) -> (int128, int128):
    self.a = inp
    memory: int128  = convert(inp, int128)
    storage: int128 = convert(self.a, int128)
    return  memory, storage

@public
def bytes32_to_num() -> (int128, int128):
    self.b = 0x0000000000000000000000000000000000000000000000000000000000000001
    literal: int128 = convert(0x0000000000000000000000000000000000000000000000000000000000000001, int128)  # noqa: E501
    storage: int128 = convert(self.b, int128)
    return literal, storage

@public
def bytes_to_num() -> (int128, int128):
    self.c = 'a'
    literal: int128 = convert('a', int128)
    storage: int128 = convert(self.c, int128)
    return literal, storage

@public
def zero_bytes(inp: bytes[1]) -> int128:
    return convert(inp, int128)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.uint256_to_num(1) == [1, 1]
    assert c.bytes32_to_num() == [1, 1]
    assert c.bytes_to_num() == [97, 97]

    assert c.zero_bytes(b'\x01') == 1
    assert c.zero_bytes(b'\x00') == 0


def test_convert_from_bytes(assert_compile_failed,
                            assert_tx_failed,
                            get_contract_with_gas_estimation):
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
astor: bytes[10]

@public
def bar_storage() -> int128:
    self.astor = "a"
    return convert(self.astor, int128)
    """

    c = get_contract_with_gas_estimation(bytes_to_num_code)
    assert c.bar_storage() == 97

    # Test overflow bytes input for conversion
    test_fail = """
@public
def foo(bar: bytes[33]) -> int128:
    return convert(bar, int128)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(test_fail),
        TypeMismatchException
    )

    test_fail = """
@public
def foobar() -> int128:
    barfoo: bytes[63] = "Hello darkness, my old friend I've come to talk with you again."
    return convert(barfoo, int128)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(test_fail),
        TypeMismatchException
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


def test_convert_from_uint256(get_contract_with_gas_estimation):
    code = """
@public
def test(foo: uint256) -> int128:
    return convert(foo, int128)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.test(0) == 0
    assert c.test(2**127 - 1) == 2**127 - 1


def test_out_of_range_from_uint256(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def test(foo: uint256) -> int128:
    return convert(foo, int128)
    """

    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.test(2**127))
    assert_tx_failed(lambda: c.test(2**256 - 1))


def test_out_of_range_from_uint256_at_compile(assert_compile_failed,
                                              get_contract_with_gas_estimation):
    code = """
@public
def test() -> int128:
    return convert(2**127, int128)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code),
        InvalidLiteralException
    )

    code = """
@public
def test() -> int128:
    return convert(2**256 - 1, int128)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code),
        InvalidLiteralException
    )


def test_convert_from_bytes32_overflow(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def test1():
    y: bytes32 = 0x1000000000000000000000000000000000000000000000000000000000000000
    x: int128 = convert(y, int128)
    """

    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.test1())


def test_convert_from_address(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def test2():
    x: int128 = convert(msg.sender, int128)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)


def test_convert_out_of_range_literal(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
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

@public
def foo() -> int128:
    return convert(27.2319, int128)

@public
def hoo() -> int128:
    return convert(-432.298391, int128)

@public
def goo() -> int128:
    return convert(0.1234, int128)

@public
def foobar() -> int128:
    self.bar = 27.2319
    return convert(self.bar, int128)

@public
def hoonar() -> int128:
    self.nar = -432.298391
    return convert(self.nar, int128)

@public
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


def test_convert_from_overflow_decimal(assert_compile_failed,
                                       assert_tx_failed,
                                       get_contract_with_gas_estimation):
    code = """
@public
def foo() -> int128:
    return convert(180141183460469231731687303715884105728.0, int128)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code),
        InvalidLiteralException
    )

    code = """
@public
def foo() -> int128:
    return convert(-180141183460469231731687303715884105728.0, int128)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code),
        InvalidLiteralException
    )
