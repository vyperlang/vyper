import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_return_type():
    long_string = 35 * "test"

    code = """
chunk: {
    a: bytes <= 8,
    b: bytes <= 8,
    c: num
}

def __init__():
    self.chunk.a = "hello"
    self.chunk.b = "world"
    self.chunk.c = 5678

def out() -> (num, address):
    return 3333, 0x0000000000000000000000000000000000000001

def out_literals() -> (num, address, bytes <= 4):
    return 1, 0x0000000000000000000000000000000000000000, "random"

def out_bytes_first() -> (bytes <= 4, num):
    return "test", 1234

def out_bytes_a(x: num, y: bytes <= 4) -> (num, bytes <= 4):
    return x, y

def out_bytes_b(x: num, y: bytes <= 4) -> (bytes <= 4, num, bytes <= 4):
    return y, x, y

def four() -> (num, bytes <= 8, bytes <= 8, num):
    return 1234, "bytes", "test", 4321


def out_chunk() -> (bytes <= 8, num, bytes <= 8):
    return self.chunk.a, self.chunk.c, self.chunk.b

def out_very_long_bytes() -> (num, bytes <= 1024, num, address):
    return 5555, "testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttest", 6666, 0x0000000000000000000000000000000000001234  # noqa
    """

    c = get_contract(code)

    assert c.out() == [3333, "0x0000000000000000000000000000000000000001"]
    assert c.out_literals() == [1, "0x0000000000000000000000000000000000000000", b"random"]
    assert c.out_bytes_first() == [b"test", 1234]
    assert c.out_bytes_a(5555555, "test") == [5555555, b"test"]
    assert c.out_bytes_b(5555555, "test") == [b"test", 5555555, b"test"]
    assert c.four() == [1234, b"bytes", b"test", 4321]
    assert c.out_chunk() == [b"hello", 5678, b"world"]
    assert c.out_very_long_bytes() == [5555, long_string.encode(), 6666, "0x0000000000000000000000000000000000001234"]
