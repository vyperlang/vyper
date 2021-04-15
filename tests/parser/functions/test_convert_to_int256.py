from vyper.exceptions import OverflowException, TypeMismatch


def test_convert_to_int256(get_contract_with_gas_estimation):
    code = """
a: uint256
b: bytes32
c: Bytes[1]

@external
def uint256_to_num(inp: uint256) -> (int256, int256):
    self.a = inp
    memory: int256  = convert(inp, int256)
    storage: int256 = convert(self.a, int256)
    return  memory, storage

@external
def bytes32_to_num() -> (int256, int256):
    self.b = 0x0000000000000000000000000000000000000000000000000000000000000001
    literal: int256 = convert(0x0000000000000000000000000000000000000000000000000000000000000001, int256)  # noqa: E501
    storage: int256 = convert(self.b, int256)
    return literal, storage

@external
def bytes_to_num() -> (int256, int256):
    self.c = b'a'
    literal: int256 = convert('a', int256)
    storage: int256 = convert(self.c, int256)
    return literal, storage

@external
def zero_bytes(inp: Bytes[1]) -> int256:
    return convert(inp, int256)
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
def foo(bar: Bytes[5]) -> int256:
    return convert(bar, int256)
    """

    c = get_contract_with_gas_estimation(test_success)
    assert c.foo(b"\x00\x00\x00\x00\x00") == 0
    assert c.foo(b"\x00\x07\x5B\xCD\x15") == 123456789

    test_success = """
@external
def foo(bar: Bytes[32]) -> int256:
    return convert(bar, int256)
    """

    c = get_contract_with_gas_estimation(test_success)
    assert c.foo(b"") == 0
    assert c.foo(b"\x00") == 0
    assert c.foo(b"\x01") == 1
    assert c.foo(b"\x00\x01") == 1
    assert c.foo(b"\x01\x00") == 256
    assert c.foo(b"\x01\x00\x00\x00\x01") == 4294967297
    assert c.foo(b"\xff" * 32) == -1
    assert c.foo(b"\x80" + b"\x00" * 31) == -(2 ** 255)
    assert_tx_failed(lambda: c.foo(b"\x01" * 33))

    bytes_to_num_code = """
astor: Bytes[10]

@external
def bar_storage() -> int256:
    self.astor = b"a"
    return convert(self.astor, int256)
    """

    c = get_contract_with_gas_estimation(bytes_to_num_code)
    assert c.bar_storage() == 97

    # Test overflow bytes input for conversion
    test_fail = """
@external
def foo(bar: Bytes[33]) -> int256:
    return convert(bar, int256)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(test_fail), TypeMismatch)

    test_fail = """
@external
def foobar() -> int256:
    barfoo: Bytes[63] = b"Hello darkness, my old friend I've come to talk with you again."
    return convert(barfoo, int256)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(test_fail), TypeMismatch,
    )


def test_convert_from_bool(get_contract_with_gas_estimation):
    code = """
@external
def from_bool(flag: bool) -> int256:
    flagInt: int256 = convert(flag, int256)
    return flagInt
    """

    c = get_contract_with_gas_estimation(code)
    assert c.from_bool(False) == 0
    assert c.from_bool(True) == 1


def test_convert_from_uint256(get_contract_with_gas_estimation):
    code = """
@external
def test(foo: uint256) -> int256:
    return convert(foo, int256)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.test(0) == 0
    assert c.test(2 ** 127 - 1) == 2 ** 127 - 1


def test_out_of_range_from_uint256(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@external
def test(foo: uint256) -> int256:
    return convert(foo, int256)
    """

    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.test(2 ** 255))
    assert_tx_failed(lambda: c.test(2 ** 256 - 1))


def test_convert_from_bytes32(get_contract_with_gas_estimation):
    code = """
@external
def test1(y: bytes32) -> int256:
    return convert(y, int256)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.test1("0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF") == -1


def test_convert_out_of_range_literal(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@external
def test2():
    x: int256
    x = convert(340282366920938463463374607431768211459, int256)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)


def test_convert_from_decimal(get_contract_with_gas_estimation):
    code = """
bar: decimal
nar: decimal
mar: decimal

@external
def foo() -> int256:
    return convert(27.2319, int256)

@external
def hoo() -> int256:
    return convert(-432.298391, int256)

@external
def goo() -> int256:
    return convert(0.1234, int256)

@external
def foobar() -> int256:
    self.bar = 27.2319
    return convert(self.bar, int256)

@external
def hoonar() -> int256:
    self.nar = -432.298391
    return convert(self.nar, int256)

@external
def goomar() -> int256:
    self.mar = 0.1234
    return convert(self.mar, int256)
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
def foo() -> int256:
    return convert(180141183460469231731687303715884105728.0, int256)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code), OverflowException,
    )

    code = """
@external
def foo() -> int256:
    return convert(-180141183460469231731687303715884105728.0, int256)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code), OverflowException,
    )
