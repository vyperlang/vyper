
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
    assert c.address_to_bytes32(w3.eth.accounts[0]) == [bytes_helper('', 12) + w3.toBytes(hexstr=w3.eth.accounts[0])] * 2
    assert c.bytes_to_bytes32(bytes_helper('', 32)) == [bytes_helper('', 32)] * 2
    assert c.bytes_to_bytes32_from_smaller(b'hello') == bytes_helper('hello', 32)


def test_convert_from_address(get_contract_with_gas_estimation):
    test_address = "0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7"
    test_bytes = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xF5\xD4\x02\x0d\xCA\x6a\x62\xbB\x1e\xfF\xcC\x92\x12\xAA\xF3\xc9\x81\x9E\x30\xD7"

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
