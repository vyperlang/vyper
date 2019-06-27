
def test_convert_to_bytes32(w3, get_contract_with_gas_estimation, bytes_helper):
    code = """
a: int128
b: uint256
c: address
d: bytes[32]

@public
def int128_to_bytes32(inp: int128) -> (bytes32, bytes32, bytes32):
    self.a = inp
    memory: bytes32 = convert(inp, bytes32)
    storage: bytes32 = convert(self.a, bytes32)
    literal: bytes32 = convert(1, bytes32)
    return  memory, storage, literal

@public
def uint256_to_bytes32(inp: uint256) -> (bytes32, bytes32, bytes32):
    self.b = inp
    memory: bytes32 = convert(inp, bytes32)
    storage: bytes32 = convert(self.b, bytes32)
    literal: bytes32 = convert(1, bytes32)
    return  memory, storage, literal

@public
def address_to_bytes32(inp: address) -> (bytes32, bytes32):
    self.c = inp
    memory: bytes32 = convert(inp, bytes32)
    storage: bytes32 = convert(self.c, bytes32)
    return  memory, storage

@public
def bytes_to_bytes32(inp: bytes[32]) -> (bytes32, bytes32):
    self.d = inp
    memory: bytes32 = convert(inp, bytes32)
    storage: bytes32 = convert(self.d, bytes32)
    return  memory, storage

@public
def bytes_to_bytes32_from_smaller(inp: bytes[10]) -> bytes32:
    memory: bytes32 = convert(inp, bytes32)
    return memory
    """

    c = get_contract_with_gas_estimation(code)
    assert c.int128_to_bytes32(1) == [bytes_helper('', 31) + b'\x01'] * 3
    assert c.uint256_to_bytes32(1) == [bytes_helper('', 31) + b'\x01'] * 3
    assert c.address_to_bytes32(w3.eth.accounts[0]) == [bytes_helper('', 12) + w3.toBytes(hexstr=w3.eth.accounts[0])] * 2  # noqa: E501
    assert c.bytes_to_bytes32(bytes_helper('', 32)) == [bytes_helper('', 32)] * 2
    assert c.bytes_to_bytes32_from_smaller(b'hello') == bytes_helper('hello', 32)


def test_convert_from_address(get_contract_with_gas_estimation):
    test_address = "0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7"
    test_bytes = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xF5\xD4\x02\x0d\xCA\x6a\x62\xbB\x1e\xfF\xcC\x92\x12\xAA\xF3\xc9\x81\x9E\x30\xD7"  # noqa: E501

    test_address_to_bytes = """
@public
def test_address_to_bytes(x: address) -> bytes32:
    return convert(x, bytes32)
    """

    c = get_contract_with_gas_estimation(test_address_to_bytes)
    assert c.test_address_to_bytes(test_address) == test_bytes


def test_convert_from_bool(get_contract_with_gas_estimation):
    exp_code = """
@public
def testConvertBytes32(flag: bool) -> bytes32:
    flagBytes: bytes32 = convert(flag, bytes32)
    return flagBytes
    """

    c = get_contract_with_gas_estimation(exp_code)
    falseBytes = c.testConvertBytes32(False)
    assert falseBytes[31:32] == b'\x00'
    assert len(falseBytes) == 32

    trueBytes = c.testConvertBytes32(True)
    assert trueBytes[31:32] == b'\x01'
    assert len(trueBytes) == 32


#################################################################################
# NOTE: Vyper uses a decimal divisor of 10000000000 (or 10^10).
#
#       This means that `decimal` type variables can store values
#       that are of 1/10000000000.
#
#       Because of this, when converting from `decimal` to `bytes32`,
#       the conversion can be thought of as converting integer result of
#       the decimal value of interest multiplied by 10000000000.
#
#       For example, converting the decimal value `5.0` to `byte32`
#       can be thought of as giving the `bytes32` value of the integer
#       result of 5 * 10000000000 = 50000000000
#################################################################################
def test_convert_from_decimal(get_contract_with_gas_estimation):
    code = """
bar: decimal
nar: decimal
mar: decimal
jar: decimal
kar: decimal

@public
def foo() -> bytes32:
    return convert(0.0, bytes32)

@public
def foobar() -> bytes32:
    self.bar = 0.0
    return convert(self.bar, bytes32)

@public
def hoo() -> bytes32:
    return convert(MIN_DECIMAL, bytes32)

@public
def hoonar() -> bytes32:
    self.nar = MIN_DECIMAL
    return convert(self.nar, bytes32)

@public
def goo() -> bytes32:
    return convert(MAX_DECIMAL, bytes32)

@public
def goomar() -> bytes32:
    self.mar = MAX_DECIMAL
    return convert(self.mar, bytes32)

@public
def zoo() -> bytes32:
    return convert(5.0, bytes32)

@public
def zoojar() -> bytes32:
    self.jar = 5.0
    return convert(self.jar, bytes32)

@public
def xoo() -> bytes32:
    return convert(-5.0, bytes32)

@public
def xookar() -> bytes32:
    self.kar = -5.0
    return convert(self.kar, bytes32)
    """

    c = get_contract_with_gas_estimation(code)
    decimal_divisor = 10000000000

    fooVal = c.foo()
    foobarVal = c.foobar()
    assert fooVal == (b"\x00" * 32)
    assert len(fooVal) == 32
    assert foobarVal == (b"\x00" * 32)
    assert len(foobarVal) == 32
    assert fooVal == foobarVal

    hooVal = c.hoo()
    hoonarVal = c.hoonar()
    _hoo = ((-2**127) * 10000000000).to_bytes(32, byteorder="big", signed=True)
    assert hooVal == _hoo
    assert hoonarVal == _hoo

    gooVal = c.goo()
    goomarVal = c.goomar()
    _goo = ((2**127 - 1) * 10000000000).to_bytes(32, byteorder="big", signed=True)
    assert gooVal == _goo
    assert goomarVal == _goo

    zooVal = c.zoo()
    zoojarVal = c.zoojar()
    _zoo = (5 * 10000000000).to_bytes(32, byteorder="big", signed=True)
    assert zooVal == _zoo
    assert zoojarVal == _zoo

    xooVal = c.xoo()
    xookarVal = c.xookar()
    _xoo = (-5 * 10000000000).to_bytes(32, byteorder="big", signed=True)
    assert xooVal == _xoo
    assert xookarVal == _xoo
