from vyper.utils import DECIMAL_DIVISOR, SizeLimits


def test_convert_to_bytes32(w3, get_contract_with_gas_estimation, bytes_helper):
    code = """
a: int128
b: uint256
c: address
d: Bytes[32]
e: int256

@external
def int128_to_bytes32(inp: int128) -> (bytes32, bytes32, bytes32):
    self.a = inp
    memory: bytes32 = convert(inp, bytes32)
    storage: bytes32 = convert(self.a, bytes32)
    literal: bytes32 = convert(1, bytes32)
    return  memory, storage, literal


@external
def int256_to_bytes32(inp: int256) -> (bytes32, bytes32, bytes32):
    self.e = inp
    memory: bytes32 = convert(inp, bytes32)
    storage: bytes32 = convert(self.e, bytes32)
    literal: bytes32 = convert(1, bytes32)
    return  memory, storage, literal

@external
def uint256_to_bytes32(inp: uint256) -> (bytes32, bytes32, bytes32):
    self.b = inp
    memory: bytes32 = convert(inp, bytes32)
    storage: bytes32 = convert(self.b, bytes32)
    literal: bytes32 = convert(1, bytes32)
    return  memory, storage, literal

@external
def address_to_bytes32(inp: address) -> (bytes32, bytes32):
    self.c = inp
    memory: bytes32 = convert(inp, bytes32)
    storage: bytes32 = convert(self.c, bytes32)
    return  memory, storage

@external
def bytes_to_bytes32(inp: Bytes[32]) -> (bytes32, bytes32):
    self.d = inp
    memory: bytes32 = convert(inp, bytes32)
    storage: bytes32 = convert(self.d, bytes32)
    return  memory, storage

@external
def bytes_to_bytes32_from_smaller(inp: Bytes[10]) -> bytes32:
    memory: bytes32 = convert(inp, bytes32)
    return memory
    """

    c = get_contract_with_gas_estimation(code)
    assert c.int128_to_bytes32(1) == [bytes_helper("", 31) + b"\x01"] * 3
    assert c.int256_to_bytes32(1) == [bytes_helper("", 31) + b"\x01"] * 3
    assert c.uint256_to_bytes32(1) == [bytes_helper("", 31) + b"\x01"] * 3
    assert (
        c.address_to_bytes32(w3.eth.accounts[0])
        == [bytes_helper("", 12) + w3.toBytes(hexstr=w3.eth.accounts[0])] * 2
    )  # noqa: E501
    assert c.bytes_to_bytes32(bytes_helper("", 32)) == [bytes_helper("", 32)] * 2
    assert c.bytes_to_bytes32_from_smaller(b"hello") == bytes_helper("hello", 32)


def test_convert_from_address(get_contract_with_gas_estimation):
    test_address = "0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7"
    test_bytes = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xF5\xD4\x02\x0d\xCA\x6a\x62\xbB\x1e\xfF\xcC\x92\x12\xAA\xF3\xc9\x81\x9E\x30\xD7"  # noqa: E501

    test_address_to_bytes = """
@external
def test_address_to_bytes(x: address) -> bytes32:
    return convert(x, bytes32)
    """

    c = get_contract_with_gas_estimation(test_address_to_bytes)
    assert c.test_address_to_bytes(test_address) == test_bytes


def test_convert_from_bool(get_contract_with_gas_estimation):
    exp_code = """
@external
def testConvertBytes32(flag: bool) -> bytes32:
    flagBytes: bytes32 = convert(flag, bytes32)
    return flagBytes
    """

    c = get_contract_with_gas_estimation(exp_code)
    falseBytes = c.testConvertBytes32(False)
    assert falseBytes[31:32] == b"\x00"
    assert len(falseBytes) == 32

    trueBytes = c.testConvertBytes32(True)
    assert trueBytes[31:32] == b"\x01"
    assert len(trueBytes) == 32


def int_to_bytes_helper(val):
    return (val).to_bytes(32, byteorder="big", signed=True)


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
temp: decimal

@external
def convert_literal_zero() -> bytes32:
    return convert(0.0, bytes32)

@external
def convert_literal_zero_storage() -> bytes32:
    self.temp = 0.0
    return convert(self.temp, bytes32)

@external
def convert_min_decimal() -> bytes32:
    return convert(MIN_DECIMAL, bytes32)

@external
def convert_min_decimal_storage() -> bytes32:
    self.temp = MIN_DECIMAL
    return convert(self.temp, bytes32)

@external
def convert_max_decimal() -> bytes32:
    return convert(MAX_DECIMAL, bytes32)

@external
def convert_max_decimal_storage() -> bytes32:
    self.temp = MAX_DECIMAL
    return convert(self.temp, bytes32)

@external
def convert_positive_decimal() -> bytes32:
    return convert(5.0, bytes32)

@external
def convert_positive_decimal_storage() -> bytes32:
    self.temp = 5.0
    return convert(self.temp, bytes32)

@external
def convert_negative_decimal() -> bytes32:
    return convert(-5.0, bytes32)

@external
def convert_negative_decimal_storage() -> bytes32:
    self.temp = -5.0
    return convert(self.temp, bytes32)
    """

    c = get_contract_with_gas_estimation(code)

    _temp = b"\x00" * 32
    assert _temp == c.convert_literal_zero()
    assert _temp == c.convert_literal_zero_storage()

    _temp = int_to_bytes_helper(SizeLimits.MINDECIMAL)
    assert _temp == c.convert_min_decimal()
    assert _temp == c.convert_min_decimal_storage()

    _temp = int_to_bytes_helper(SizeLimits.MAXDECIMAL)
    assert _temp == c.convert_max_decimal()
    assert _temp == c.convert_max_decimal_storage()

    _temp = int_to_bytes_helper(5 * DECIMAL_DIVISOR)
    assert _temp == c.convert_positive_decimal()
    assert _temp == c.convert_positive_decimal_storage()

    _temp = int_to_bytes_helper(-5 * DECIMAL_DIVISOR)
    assert _temp == c.convert_negative_decimal()
    assert _temp == c.convert_negative_decimal_storage()
