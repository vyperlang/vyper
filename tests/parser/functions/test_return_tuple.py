def test_return_type(get_contract_with_gas_estimation):
    long_string = 35 * "test"

    code = """
chunk: {
    a: bytes <= 8,
    b: bytes <= 8,
    c: num
}

@public
def __init__():
    self.chunk.a = "hello"
    self.chunk.b = "world"
    self.chunk.c = 5678

@public
def out() -> (num, address):
    return 3333, 0x0000000000000000000000000000000000000001

@public
def out_literals() -> (num, address, bytes <= 4):
    return 1, 0x0000000000000000000000000000000000000000, "random"

@public
def out_bytes_first() -> (bytes <= 4, num):
    return "test", 1234

@public
def out_bytes_a(x: num, y: bytes <= 4) -> (num, bytes <= 4):
    return x, y

@public
def out_bytes_b(x: num, y: bytes <= 4) -> (bytes <= 4, num, bytes <= 4):
    return y, x, y

@public
def four() -> (num, bytes <= 8, bytes <= 8, num):
    return 1234, "bytes", "test", 4321

@public
def out_chunk() -> (bytes <= 8, num, bytes <= 8):
    return self.chunk.a, self.chunk.c, self.chunk.b

@public
def out_very_long_bytes() -> (num, bytes <= 1024, num, address):
    return 5555, "testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttest", 6666, 0x0000000000000000000000000000000000001234  # noqa
    """

    c = get_contract_with_gas_estimation(code)

    assert c.out() == [3333, "0x0000000000000000000000000000000000000001"]
    assert c.out_literals() == [1, "0x0000000000000000000000000000000000000000", b"random"]
    assert c.out_bytes_first() == [b"test", 1234]
    assert c.out_bytes_a(5555555, "test") == [5555555, b"test"]
    assert c.out_bytes_b(5555555, "test") == [b"test", 5555555, b"test"]
    assert c.four() == [1234, b"bytes", b"test", 4321]
    assert c.out_chunk() == [b"hello", 5678, b"world"]
    assert c.out_very_long_bytes() == [5555, long_string.encode(), 6666, "0x0000000000000000000000000000000000001234"]


def test_return_type_signatures(get_contract_with_gas_estimation):
    code = """
@public
def out_literals() -> (num, address, bytes <= 4):
    return 1, 0x0000000000000000000000000000000000000000, "random"
    """

    c = get_contract_with_gas_estimation(code)
    assert c.translator.function_data['out_literals']['decode_types'] == ['int128', 'address', 'bytes']
