from vyper.exceptions import (
    TypeMismatch,
)


def test_return_type(get_contract_with_gas_estimation):
    long_string = 35 * "test"

    code = """
struct Chunk:
    a: bytes[8]
    b: bytes[8]
    c: int128
chunk: Chunk

@public
def __init__():
    self.chunk.a = "hello"
    self.chunk.b = "world"
    self.chunk.c = 5678

@public
def out() -> (int128, address):
    return 3333, 0x0000000000000000000000000000000000000001

@public
def out_literals() -> (int128, address, bytes[6]):
    return 1, 0x0000000000000000000000000000000000000000, b"random"

@public
def out_bytes_first() -> (bytes[4], int128):
    return b"test", 1234

@public
def out_bytes_a(x: int128, y: bytes[4]) -> (int128, bytes[4]):
    return x, y

@public
def out_bytes_b(x: int128, y: bytes[4]) -> (bytes[4], int128, bytes[4]):
    return y, x, y

@public
def four() -> (int128, bytes[8], bytes[8], int128):
    return 1234, b"bytes", b"test", 4321

@public
def out_chunk() -> (bytes[8], int128, bytes[8]):
    return self.chunk.a, self.chunk.c, self.chunk.b

@public
def out_very_long_bytes() -> (int128, bytes[1024], int128, address):
    return 5555, b"testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttest", 6666, 0x0000000000000000000000000000000000001234  # noqa
    """

    c = get_contract_with_gas_estimation(code)

    assert c.out() == [3333, "0x0000000000000000000000000000000000000001"]
    assert c.out_literals() == [1, None, b"random"]
    assert c.out_bytes_first() == [b"test", 1234]
    assert c.out_bytes_a(5555555, b"test") == [5555555, b"test"]
    assert c.out_bytes_b(5555555, b"test") == [b"test", 5555555, b"test"]
    assert c.four() == [1234, b"bytes", b"test", 4321]
    assert c.out_chunk() == [b"hello", 5678, b"world"]
    assert c.out_very_long_bytes() == [
        5555, long_string.encode(), 6666, "0x0000000000000000000000000000000000001234"
    ]


def test_return_type_signatures(get_contract_with_gas_estimation):
    code = """
@public
def out_literals() -> (int128, address, bytes[6]):
    return 1, 0x0000000000000000000000000000000000000000, b"random"
    """

    c = get_contract_with_gas_estimation(code)
    assert c._classic_contract.abi[0]['outputs'] == [
        {'type': 'int128', 'name': ''},
        {'type': 'address', 'name': ''},
        {'type': 'bytes', 'name': ''},
    ]


def test_return_tuple_assign(get_contract_with_gas_estimation):
    code = """
@private
def _out_literals() -> (int128, address, bytes[10]):
    return 1, 0x0000000000000000000000000000000000000000, b"random"

@public
def out_literals() -> (int128, address, bytes[10]):
    return self._out_literals()

@public
def test() -> (int128, address, bytes[10]):
    a: int128 = 0
    b: address = ZERO_ADDRESS
    c: bytes[10] = b""
    (a, b, c) = self._out_literals()
    return a, b, c
    """

    c = get_contract_with_gas_estimation(code)

    assert c.out_literals() == c.test() == [1, None, b"random"]


def test_return_tuple_assign_storage(get_contract_with_gas_estimation):
    code = """
a: int128
b: address
c: bytes[20]
d: bytes[20]

@private
def _out_literals() -> (int128, bytes[20], address, bytes[20]):
    return 1, b"testtesttest", 0x0000000000000000000000000000000000000023, b"random"

@public
def out_literals() -> (int128, bytes[20], address, bytes[20]):
    return self._out_literals()

@public
def test1() -> (int128, bytes[20], address, bytes[20]):
    self.a, self.c, self.b, self.d = self._out_literals()
    return self.a, self.c, self.b, self.d

@public
def test2() -> (int128, address):
    x: int128 = 0
    x, self.c, self.b, self.d = self._out_literals()
    return x, self.b

@public
def test3() -> (address, int128):
    x: address = ZERO_ADDRESS
    self.a, self.c, x, self.d = self._out_literals()
    return x, self.a
    """

    c = get_contract_with_gas_estimation(code)

    addr = '0x' + '00' * 19 + '23'
    assert c.out_literals() == [1, b"testtesttest", addr, b"random"]
    assert c.out_literals() == c.test1()
    assert c.test2() == [1, c.out_literals()[2]]
    assert c.test3() == [c.out_literals()[2], 1]


def test_tuple_return_typecheck(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def getTimeAndBalance() -> (bool, address):
    return block.timestamp, self.balance
    """

    assert_tx_failed(lambda: get_contract_with_gas_estimation(code), TypeMismatch)
