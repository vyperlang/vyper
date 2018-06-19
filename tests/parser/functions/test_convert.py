from decimal import Decimal


def test_convert_to_num(get_contract_with_gas_estimation, assert_tx_failed):
    code = """
a: uint256
b: bytes32
c: bytes[1]

@public
def uint256_to_num(inp: uint256) -> (int128, int128):
    self.a = inp
    memory: int128  = convert(inp, 'int128')
    storage: int128 = convert(self.a, 'int128')
    return  memory, storage

@public
def bytes32_to_num() -> (int128, int128):
    self.b = 0x0000000000000000000000000000000000000000000000000000000000000001
    literal: int128 = convert(0x0000000000000000000000000000000000000000000000000000000000000001, 'int128')
    storage: int128 = convert(self.b, 'int128')
    return literal, storage

@public
def bytes_to_num() -> (int128, int128):
    self.c = 'a'
    literal: int128 = convert('a', 'int128')
    storage: int128 = convert(self.c, 'int128')
    return literal, storage

@public
def zero_bytes(inp: bytes[1]) -> int128:
    return convert(inp, 'int128')
"""
    c = get_contract_with_gas_estimation(code)
    assert c.uint256_to_num(1) == [1, 1]
    assert c.bytes32_to_num() == [1, 1]
    assert c.bytes_to_num() == [97, 97]

    assert c.zero_bytes(b'\x01') == 1
    assert c.zero_bytes(b'\x00') == 0


def test_convert_to_uint256(get_contract, assert_tx_failed):
    code = """
a: int128
b: bytes32
c: uint256
d: address

@public
def int128_to_uint256(inp: int128) -> (uint256, uint256, uint256):
    self.a = inp
    memory: uint256  = convert(inp, "uint256")
    storage: uint256 = convert(self.a, "uint256")
    literal: uint256 = convert(1, "uint256")
    return  memory, storage, literal

@public
def bytes32_to_uint256() -> (uint256, uint256):
    self.b = 0x0000000000000000000000000000000000000000000000000000000000000001
    literal: uint256 = convert(0x0000000000000000000000000000000000000000000000000000000000000001, "uint256")
    storage: uint256 = convert(self.b, "uint256")
    return literal, storage
"""
    c = get_contract(code)
    assert c.int128_to_uint256(1) == [1, 1, 1]
    assert c.bytes32_to_uint256() == [1, 1]


def test_convert_to_decimal(get_contract, assert_tx_failed):
    code = """
a: int128
b: decimal

@public
def int128_to_decimal(inp: int128) -> (decimal, decimal, decimal):
    self.a = inp
    memory: decimal = convert(inp, "decimal")
    storage: decimal = convert(self.a, "decimal")
    literal: decimal = convert(1, "decimal")
    return  memory, storage, literal
"""
    c = get_contract(code)
    assert c.int128_to_decimal(1) == [1.0, 1.0, 1.0]


def test_convert_to_bytes32(w3, get_contract_with_gas_estimation, bytes_helper):
    code = """
a: int128
b: uint256
c: address
d: bytes[32]

@public
def int128_to_bytes32(inp: int128) -> (bytes32, bytes32, bytes32):
    self.a = inp
    memory: bytes32 = convert(inp, "bytes32")
    storage: bytes32 = convert(self.a, "bytes32")
    literal: bytes32 = convert(1, "bytes32")
    return  memory, storage, literal

@public
def uint256_to_bytes32(inp: uint256) -> (bytes32, bytes32, bytes32):
    self.b = inp
    memory: bytes32 = convert(inp, "bytes32")
    storage: bytes32 = convert(self.b, "bytes32")
    literal: bytes32 = convert(1, "bytes32")
    return  memory, storage, literal

@public
def address_to_bytes32(inp: address) -> (bytes32, bytes32):
    self.c = inp
    memory: bytes32 = convert(inp, "bytes32")
    storage: bytes32 = convert(self.c, "bytes32")
    return  memory, storage

@public
def bytes_to_bytes32(inp: bytes[32]) -> (bytes32, bytes32):
    self.d = inp
    memory: bytes32 = convert(inp, "bytes32")
    storage: bytes32 = convert(self.d, "bytes32")
    return  memory, storage
"""
    c = get_contract_with_gas_estimation(code)
    assert c.int128_to_bytes32(1) == [bytes_helper('', 31) + b'\x01'] * 3
    assert c.uint256_to_bytes32(1) == [bytes_helper('', 31) + b'\x01'] * 3
    assert c.address_to_bytes32(w3.eth.accounts[0]) == [bytes_helper('', 12) + w3.toBytes(hexstr=w3.eth.accounts[0])] * 2
    assert c.bytes_to_bytes32(bytes_helper('', 32)) == [bytes_helper('', 32)] * 2


def test_uint256_decimal(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def test_variable() -> bool:
    a: uint256 = 1000
    return convert(a, 'decimal') == 1000.0

@public
def test_passed_variable(a: uint256) -> decimal:
    return convert(a, 'decimal')
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test_variable() is True
    assert c.test_passed_variable(256) == 256
    max_decimal = (2**127 - 1)
    assert c.test_passed_variable(max_decimal) == Decimal(max_decimal)
    assert_tx_failed(lambda: c.test_passed_variable(max_decimal + 1))


def test_convert_to_uint256_units(get_contract, assert_tx_failed):
    code = """
units: {
    meter: "Meter"
}

@public
def test() -> int128(meter):
    b: uint256(meter) = 1234
    a: int128(meter) = convert(b, "int128")
    return a
    """

    c = get_contract(code)
    assert c.test() == 1234


def test_convert_to_int128_units(get_contract, assert_tx_failed):
    code = """
units: {
    meter: "Meter"
}

@public
def test() -> uint256(meter):
    b: int128(meter) = 4321
    a: uint256(meter) = convert(b, "uint256")
    return a
    """

    c = get_contract(code)
    assert c.test() == 4321


def test_convert_to_int128_decimal_units(get_contract, assert_tx_failed):
    code = """
units: {
    meter: "Meter"
}

@public
def test() -> decimal(meter):
    a: decimal(meter) = convert(5001, "decimal")
    return a

@public
def test2() -> decimal(meter):
    b: int128(meter) = 1234
    a: decimal(meter) = convert(b, "decimal")
    return a
    """

    c = get_contract(code)
    assert c.test() == Decimal('5001')
    assert c.test2() == Decimal('1234')


def test_convert_address_to_uint256(w3, get_contract):
    a = w3.eth.accounts[0]
    code = """
stor_a: address

@public
def conv1(a: address) -> uint256:
    return convert(a, 'uint256')

@public
def conv2() -> uint256:
    self.stor_a = 0x744d70FDBE2Ba4CF95131626614a1763DF805B9E
    return convert(self.stor_a, 'uint256')

@public
def conv3() -> uint256:
    return convert(0x744d70FDBE2Ba4CF95131626614a1763DF805B9E, 'uint256')
    """

    c = get_contract(code)

    assert c.conv1(a) == int(a, 0)
    assert c.conv2() == 663969929716095361663590611662499625636445838238
    assert c.conv3() == 663969929716095361663590611662499625636445838238
