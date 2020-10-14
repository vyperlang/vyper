import pytest

from vyper.exceptions import TypeMismatch

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_return_type(get_contract_with_gas_estimation):
    long_string = 35 * "test"

    code = """
struct Chunk:
    a: Bytes[8]
    b: Bytes[8]
    c: int128
chunk: Chunk

@external
def __init__():
    self.chunk.a = b"hello"
    self.chunk.b = b"world"
    self.chunk.c = 5678

@external
def out() -> (int128, address):
    return 3333, 0x0000000000000000000000000000000000000001

@external
def out_literals() -> (int128, address, Bytes[6]):
    return 1, 0x0000000000000000000000000000000000000000, b"random"

@external
def out_bytes_first() -> (Bytes[4], int128):
    return b"test", 1234

@external
def out_bytes_a(x: int128, y: Bytes[4]) -> (int128, Bytes[4]):
    return x, y

@external
def out_bytes_b(x: int128, y: Bytes[4]) -> (Bytes[4], int128, Bytes[4]):
    return y, x, y

@external
def four() -> (int128, Bytes[8], Bytes[8], int128):
    return 1234, b"bytes", b"test", 4321

@external
def out_chunk() -> (Bytes[8], int128, Bytes[8]):
    return self.chunk.a, self.chunk.c, self.chunk.b

@external
def out_very_long_bytes() -> (int128, Bytes[1024], int128, address):
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
        5555,
        long_string.encode(),
        6666,
        "0x0000000000000000000000000000000000001234",
    ]


def test_return_type_signatures(get_contract_with_gas_estimation):
    code = """
@external
def out_literals() -> (int128, address, Bytes[6]):
    return 1, 0x0000000000000000000000000000000000000000, b"random"
    """

    c = get_contract_with_gas_estimation(code)
    assert c._classic_contract.abi[0]["outputs"] == [
        {"type": "int128", "name": ""},
        {"type": "address", "name": ""},
        {"type": "bytes", "name": ""},
    ]


def test_return_tuple_assign(get_contract_with_gas_estimation):
    code = """
@internal
def _out_literals() -> (int128, address, Bytes[10]):
    return 1, 0x0000000000000000000000000000000000000000, b"random"

@external
def out_literals() -> (int128, address, Bytes[10]):
    return self._out_literals()

@external
def test() -> (int128, address, Bytes[10]):
    a: int128 = 0
    b: address = ZERO_ADDRESS
    c: Bytes[10] = b""
    (a, b, c) = self._out_literals()
    return a, b, c
    """

    c = get_contract_with_gas_estimation(code)

    assert c.out_literals() == c.test() == [1, None, b"random"]


def test_return_tuple_assign_storage(get_contract_with_gas_estimation):
    code = """
a: int128
b: address
c: Bytes[20]
d: Bytes[20]

@internal
def _out_literals() -> (int128, Bytes[20], address, Bytes[20]):
    return 1, b"testtesttest", 0x0000000000000000000000000000000000000023, b"random"

@external
def out_literals() -> (int128, Bytes[20], address, Bytes[20]):
    return self._out_literals()

@external
def test1() -> (int128, Bytes[20], address, Bytes[20]):
    self.a, self.c, self.b, self.d = self._out_literals()
    return self.a, self.c, self.b, self.d

@external
def test2() -> (int128, address):
    x: int128 = 0
    x, self.c, self.b, self.d = self._out_literals()
    return x, self.b

@external
def test3() -> (address, int128):
    x: address = ZERO_ADDRESS
    self.a, self.c, x, self.d = self._out_literals()
    return x, self.a
    """

    c = get_contract_with_gas_estimation(code)

    addr = "0x" + "00" * 19 + "23"
    assert c.out_literals() == [1, b"testtesttest", addr, b"random"]
    assert c.out_literals() == c.test1()
    assert c.test2() == [1, c.out_literals()[2]]
    assert c.test3() == [c.out_literals()[2], 1]


def test_tuple_return_typecheck(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@external
def getTimeAndBalance() -> (bool, address):
    return block.timestamp, self.balance
    """

    assert_tx_failed(lambda: get_contract_with_gas_estimation(code), TypeMismatch)
