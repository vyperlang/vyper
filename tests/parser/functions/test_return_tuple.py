def test_return_type(get_contract_with_gas_estimation):
    long_string = 35 * "test"

    code = """
chunk: {
    a: bytes[8],
    b: bytes[8],
    c: int128
}

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
    return 1, 0x0000000000000000000000000000000000000000, "random"

@public
def out_bytes_first() -> (bytes[4], int128):
    return "test", 1234

@public
def out_bytes_a(x: int128, y: bytes[4]) -> (int128, bytes[4]):
    return x, y

@public
def out_bytes_b(x: int128, y: bytes[4]) -> (bytes[4], int128, bytes[4]):
    return y, x, y

@public
def four() -> (int128, bytes[8], bytes[8], int128):
    return 1234, "bytes", "test", 4321

@public
def out_chunk() -> (bytes[8], int128, bytes[8]):
    return self.chunk.a, self.chunk.c, self.chunk.b

@public
def out_very_long_bytes() -> (int128, bytes[1024], int128, address):
    return 5555, "testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttest", 6666, 0x0000000000000000000000000000000000001234  # noqa
    """

    c = get_contract_with_gas_estimation(code)

    assert c.out() == [3333, "0x0000000000000000000000000000000000000001"]
    assert c.out_literals() == [1, None, b"random"]
    assert c.out_bytes_first() == [b"test", 1234]
    assert c.out_bytes_a(5555555, b"test") == [5555555, b"test"]
    assert c.out_bytes_b(5555555, b"test") == [b"test", 5555555, b"test"]
    assert c.four() == [1234, b"bytes", b"test", 4321]
    assert c.out_chunk() == [b"hello", 5678, b"world"]
    assert c.out_very_long_bytes() == [5555, long_string.encode(), 6666, "0x0000000000000000000000000000000000001234"]


def test_return_type_signatures(get_contract_with_gas_estimation):
    code = """
@public
def out_literals() -> (int128, address, bytes[6]):
    return 1, 0x0000000000000000000000000000000000000000, "random"
    """

    c = get_contract_with_gas_estimation(code)
    assert c._classic_contract.abi[0]['outputs'] == [{'type': 'int128', 'name': 'out'}, {'type': 'address', 'name': 'out'}, {'type': 'bytes', 'name': 'out'}]


def test_return_tuple_assign(get_contract_with_gas_estimation):
    code = """
@public
def out_literals() -> (int128, address, bytes[10]):
    return 1, 0x0000000000000000000000000000000000000000, "random"


@public
def test() -> (int128, address, bytes[10]):
    a: int128
    b: address
    c: bytes[10]
    (a, b, c) = self.out_literals()
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

@public
def out_literals() -> (int128, bytes[20], address, bytes[20]):
    return 1, "testtesttest", 0x0000000000000000000000000000000000000000, "random"


@public
def test() -> (int128, bytes[20], address, bytes[20]):
    self.a, self.c, self.b, self.d = self.out_literals()
    return self.a, self.c, self.b, self.d
    """

    c = get_contract_with_gas_estimation(code)

    assert c.out_literals() == [1, b"testtesttest", None, b"random"]
