from vyper.exceptions import (
    InvalidLiteralException,
)


def test_convert_to_uint256_units(get_contract, assert_tx_failed):
    code = """
units: {
    meter: "Meter"
}

@public
def test() -> int128(meter):
    b: uint256(meter) = 1234
    a: int128(meter) = convert(b, int128)
    return a
    """

    c = get_contract(code)
    assert c.test() == 1234


def test_convert_to_uint256(get_contract_with_gas_estimation):
    code = """
a: int128
b: bytes32
c: uint256
d: address

@public
def int128_to_uint256(inp: int128) -> (uint256, uint256, uint256):
    self.a = inp
    memory: uint256  = convert(inp, uint256)
    storage: uint256 = convert(self.a, uint256)
    literal: uint256 = convert(1, uint256)
    return  memory, storage, literal

@public
def bytes32_to_uint256() -> (uint256, uint256):
    self.b = 0x0000000000000000000000000000000000000000000000000000000000000001
    literal: uint256 = convert(0x0000000000000000000000000000000000000000000000000000000000000001, uint256)  # noqa: E501
    storage: uint256 = convert(self.b, uint256)
    return literal, storage
    """

    c = get_contract_with_gas_estimation(code)
    assert c.int128_to_uint256(1) == [1, 1, 1]
    assert c.bytes32_to_uint256() == [1, 1]


def test_convert_from_bytes(assert_compile_failed, get_contract_with_gas_estimation):
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


def test_convert_from_address(w3, get_contract):
    a = w3.eth.accounts[0]
    code = """
stor_a: address

@public
def conv1(a: address) -> uint256:
    return convert(a, uint256)

@public
def conv2() -> uint256:
    self.stor_a = 0x744d70FDBE2Ba4CF95131626614a1763DF805B9E
    return convert(self.stor_a, uint256)

@public
def conv3() -> uint256:
    return convert(0x744d70FDBE2Ba4CF95131626614a1763DF805B9E, uint256)
    """

    c = get_contract(code)

    assert c.conv1(a) == int(a, 0)
    assert c.conv2() == 663969929716095361663590611662499625636445838238
    assert c.conv3() == 663969929716095361663590611662499625636445838238


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


def test_convert_from_negative_num(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo() -> uint256:
    return convert(1-2, uint256)
    """
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)


def test_convert_from_negative_input(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(x: int128) -> uint256:
    return convert(x, uint256)
    """
    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.foo(-1))


def test_convert_from_bytes32(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> uint256:
    return convert(convert(-1, bytes32), uint256)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 2 ** 256 - 1


def test_convert_from_decimal(get_contract_with_gas_estimation):
    code = """
bar: decimal
nar: decimal
mar: decimal

@public
def foo() -> uint256:
    return convert(27.2319, uint256)

@public
def hoo() -> uint256:
    return convert(432.298391, uint256)

@public
def goo() -> uint256:
    return convert(0.1234, uint256)

@public
def foobar() -> uint256:
    self.bar = 27.2319
    return convert(self.bar, uint256)

@public
def hoonar() -> uint256:
    self.nar = 432.298391
    return convert(self.nar, uint256)

@public
def goomar() -> uint256:
    self.mar = 0.1234
    return convert(self.mar, uint256)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 27
    assert c.hoo() == 432
    assert c.goo() == 0
    assert c.foobar() == 27
    assert c.hoonar() == 432
    assert c.goomar() == 0


def test_convert_from_negative_decimal(assert_compile_failed,
                                       assert_tx_failed,
                                       get_contract_with_gas_estimation):
    code = """
@public
def foo() -> uint256:
    return convert(-27.2319, uint256)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code),
        InvalidLiteralException
    )

    code = """
@public
def foo() -> uint256:
    return convert(-(-(-27.2319)), uint256)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code),
        InvalidLiteralException
    )

    code = """
bar: decimal

@public
def foobar() -> uint256:
    self.bar = -27.2319
    return convert(self.bar, uint256)
    """

    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(
        lambda: c.foobar()
    )
