from vyper.exceptions import (
    TypeMismatch,
)


def test_test_bytes(get_contract_with_gas_estimation, assert_tx_failed):
    test_bytes = """
@public
def foo(x: bytes[100]) -> bytes[100]:
    return x
    """

    c = get_contract_with_gas_estimation(test_bytes)
    moo_result = c.foo(b'cow')
    assert moo_result == b'cow'

    print('Passed basic bytes test')

    assert c.foo(b'\x35' * 100) == b'\x35' * 100

    print('Passed max-length bytes test')

    # test for greater than 100 bytes, should raise exception
    assert_tx_failed(lambda: c.foo(b'\x35' * 101))

    print('Passed input-too-long test')


def test_test_bytes2(get_contract_with_gas_estimation):
    test_bytes2 = """
@public
def foo(x: bytes[100]) -> bytes[100]:
    y: bytes[100] = x
    return y
    """

    c = get_contract_with_gas_estimation(test_bytes2)
    assert c.foo(b'cow') == b'cow'
    assert c.foo(b'') == b''
    assert c.foo(b'\x35' * 63) == b'\x35' * 63
    assert c.foo(b'\x35' * 64) == b'\x35' * 64
    assert c.foo(b'\x35' * 65) == b'\x35' * 65

    print('Passed string copying test')


def test_test_bytes3(get_contract_with_gas_estimation):
    test_bytes3 = """
x: int128
maa: bytes[60]
y: int128

@public
def __init__():
    self.x = 27
    self.y = 37

@public
def set_maa(inp: bytes[60]):
    self.maa = inp

@public
def set_maa2(inp: bytes[60]):
    ay: bytes[60] = inp
    self.maa = ay

@public
def get_maa() -> bytes[60]:
    return self.maa

@public
def get_maa2() -> bytes[60]:
    ay: bytes[60] = self.maa
    return ay

@public
def get_xy() -> int128:
    return self.x * self.y
    """

    c = get_contract_with_gas_estimation(test_bytes3)
    c.set_maa(b"pig", transact={})
    assert c.get_maa() == b"pig"
    assert c.get_maa2() == b"pig"
    c.set_maa2(b"", transact={})
    assert c.get_maa() == b""
    assert c.get_maa2() == b""
    c.set_maa(b"\x44" * 60, transact={})
    assert c.get_maa() == b"\x44" * 60
    assert c.get_maa2() == b"\x44" * 60
    c.set_maa2(b"mongoose", transact={})
    assert c.get_maa() == b"mongoose"
    assert c.get_xy() == 999

    print('Passed advanced string copying test')


def test_test_bytes4(get_contract_with_gas_estimation):
    test_bytes4 = """
a: bytes[60]
@public
def foo(inp: bytes[60]) -> bytes[60]:
    self.a = inp
    self.a = b""
    return self.a

@public
def bar(inp: bytes[60]) -> bytes[60]:
    b: bytes[60] = inp
    b = b""
    return b
    """

    c = get_contract_with_gas_estimation(test_bytes4)
    assert c.foo(b"") == b"", c.foo()
    assert c.bar(b"") == b""

    print('Passed string deleting test')


def test_test_bytes5(get_contract_with_gas_estimation):
    test_bytes5 = """
struct G:
    a: bytes[50]
    b: bytes[50]
struct H:
    a: bytes[40]
    b: bytes[45]

g: G

@public
def foo(inp1: bytes[40], inp2: bytes[45]):
    self.g = G({a: inp1, b: inp2})

@public
def check1() -> bytes[50]:
    return self.g.a

@public
def check2() -> bytes[50]:
    return self.g.b

@public
def bar(inp1: bytes[40], inp2: bytes[45]) -> bytes[50]:
    h: H = H({a: inp1, b: inp2})
    return h.a

@public
def bat(inp1: bytes[40], inp2: bytes[45]) -> bytes[50]:
    h: H = H({a: inp1, b: inp2})
    return h.b

@public
def quz(inp1: bytes[40], inp2: bytes[45]):
    h:  H = H({a: inp1, b: inp2})
    self.g.a = h.a
    self.g.b = h.b
    """

    c = get_contract_with_gas_estimation(test_bytes5)
    c.foo(b"cow", b"horse", transact={})
    assert c.check1() == b"cow"
    assert c.check2() == b"horse"
    assert c.bar(b"pig", b"moose") == b"pig"
    assert c.bat(b"pig", b"moose") == b"moose"
    c.quz(b"badminton", b"fluffysheep", transact={})
    assert c.check1() == b"badminton"
    assert c.check2() == b"fluffysheep"

    print('Passed string struct test')


def test_binary_literal(get_contract_with_gas_estimation):
    bytes_to_num_code = """
r: bytes[1]

@public
def get(a: bytes[1]) -> bytes[2]:
    return concat(a, 0b00000001)

@public
def getsome() -> bytes[1]:
    return 0b00001110

@public
def testsome(a: bytes[1]) -> bool:
    return a == 0b01100001

@public
def testsome_storage(y: bytes[1]) -> bool:
    self.r = 0b01100001
    return self.r == y
    """

    c = get_contract_with_gas_estimation(bytes_to_num_code)

    assert c.getsome() == b'\x0e'
    assert c.testsome(b'a')
    assert c.testsome(b'\x61')
    assert c.testsome(0b1100001.to_bytes(1, 'big'))
    assert not c.testsome(b'b')
    assert c.testsome_storage(b'a')
    assert not c.testsome_storage(b'x')


def test_bytes_comparison(get_contract_with_gas_estimation):
    code = """
@public
def get_mismatch(a: bytes[1]) -> bool:
    b: bytes[2] = b'ab'
    return a == b

@public
def get_large(a: bytes[100]) -> bool:
    b: bytes[100] = b'ab'
    return a == b
    """

    c = get_contract_with_gas_estimation(code)
    assert c.get_mismatch(b'\x00') is False
    assert c.get_large(b'\x00') is False
    assert c.get_large(b'ab') is True


def test_bytes32_literals(get_contract):
    code = """
@public
def test() -> bool:
    l: bytes32 = b'\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x80\\xac\\x58\\xcd'  # noqa: E501
    j: bytes32 = 0x0000000000000000000000000000000000000000000000000000000080ac58cd
    return l == j

    """

    c = get_contract(code)

    assert c.test() is True


def test_zero_padding_with_private(get_contract):
    code = """
counter: uint256

@private
@constant
def to_little_endian_64(_value: uint256) -> bytes[8]:
    y: uint256 = 0
    x: uint256 = _value
    for _ in range(8):
        y = shift(y, 8)
        y = y + bitwise_and(x, 255)
        x = shift(x, -8)
    return slice(convert(y, bytes32), 24, 8)

@public
def set_count(i: uint256):
    self.counter = i

@public
@constant
def get_count() -> bytes[24]:
    return self.to_little_endian_64(self.counter)
    """

    c = get_contract(code)

    assert c.get_count() == b'\x00\x00\x00\x00\x00\x00\x00\x00'
    c.set_count(1, transact={})
    assert c.get_count() == b'\x01\x00\x00\x00\x00\x00\x00\x00'
    c.set_count(0xf0f0f0, transact={})
    assert c.get_count() == b'\xf0\xf0\xf0\x00\x00\x00\x00\x00'
    c.set_count(0x0101010101010101, transact={})
    assert c.get_count() == b'\x01\x01\x01\x01\x01\x01\x01\x01'


def test_bytes_to_bytes32_assigment(get_contract, assert_compile_failed):
    code = """
@public
def assign():
    xs: bytes[32] = b'abcdef'
    y: bytes32 = xs
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)
