def test_convert_to_num(chain, get_contract_with_gas_estimation, assert_tx_failed):
    code = """
a: num
b: num256
c: bytes32
d: bytes <= 1

@public
def num_to_num(inp: num) -> (num, num, num):
    self.a = inp
    memory: num  = convert(inp, "num")
    storage: num = convert(self.a, "num")
    literal: num = convert(1, "num")
    return  memory, storage, literal

@public
def num256_to_num(inp: num256) -> (num256, num256):
    self.b = inp
    memory: num  = convert(inp, "num")
    storage: num = convert(self.b, "num")
    return  memory, storage

@public
def bytes32_to_num() -> (num, num):
    self.c = 0x0000000000000000000000000000000000000000000000000000000000000001
    literal: num = convert(0x0000000000000000000000000000000000000000000000000000000000000001, "num")
    storage: num = convert(self.c, "num")
    return literal, storage

@public
def bytes_to_num() -> (num, num):
    self.d = 'a'
    literal: num = convert('a', "num")
    storage: num = convert(self.d, "num")
    return literal, storage
"""
    c = get_contract_with_gas_estimation(code)
    assert c.num_to_num(1) == [1, 1, 1]
    assert c.num256_to_num(1) == [1, 1]
    assert c.bytes32_to_num() == [1, 1]
    assert c.bytes_to_num() == [97, 97]


def test_convert_to_num256(t, chain, get_contract, utils, assert_tx_failed):
    code = """
a: num
b: bytes32
c: num256
d: address

@public
def num_to_num256(inp: num) -> (num256, num256, num256):
    self.a = inp
    memory: num256  = convert(inp, "num256")
    storage: num256 = convert(self.a, "num256")
    literal: num256 = convert(1, "num256")
    return  memory, storage, literal

@public
def bytes32_to_num256() -> (num256, num256):
    self.b = 0x0000000000000000000000000000000000000000000000000000000000000001
    literal: num256 = convert(0x0000000000000000000000000000000000000000000000000000000000000001, "num256")
    storage: num256 = convert(self.b, "num256")
    return literal, storage
"""
    c = get_contract(code)
    assert c.num_to_num256(1) == [1, 1, 1]
    assert c.bytes32_to_num256() == [1, 1]


def test_convert_to_decimal(t, chain, get_contract, utils, assert_tx_failed):
    code = """
a: num
b: decimal

@public
def num_to_decimal(inp: num) -> (decimal, decimal, decimal):
    self.a = inp
    memory: decimal = convert(inp, "decimal")
    storage: decimal = convert(self.a, "decimal")
    literal: decimal = convert(1, "decimal")
    return  memory, storage, literal
"""
    c = get_contract(code)
    assert c.num_to_decimal(1) == [1.0, 1.0, 1.0]


def test_convert_to_bytes32(t, get_contract_with_gas_estimation, bytes_helper):
    code = """
a: num
b: num256
c: address
d: bytes <= 32

@public
def num_to_bytes32(inp: num) -> (bytes32, bytes32, bytes32):
    self.a = inp
    memory: bytes32 = convert(inp, "bytes32")
    storage: bytes32 = convert(self.a, "bytes32")
    literal: bytes32 = convert(1, "bytes32")
    return  memory, storage, literal

@public
def num256_to_bytes32(inp: num256) -> (bytes32, bytes32, bytes32):
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
def bytes_to_bytes32(inp: bytes <= 32) -> (bytes32, bytes32):
    self.d = inp
    memory: bytes32 = convert(inp, "bytes32")
    storage: bytes32 = convert(self.d, "bytes32")
    return  memory, storage
"""
    c = get_contract_with_gas_estimation(code)
    assert c.num_to_bytes32(1) == [bytes_helper('', 31) + b'\x01'] * 3
    assert c.num256_to_bytes32(1) == [bytes_helper('', 31) + b'\x01'] * 3
    assert c.address_to_bytes32(t.a0) == [bytes_helper('', 12) + t.a0] * 2
    assert c.bytes_to_bytes32(bytes_helper('', 32)) == [bytes_helper('', 32)] * 2
