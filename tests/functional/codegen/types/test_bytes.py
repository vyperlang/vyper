import pytest

from vyper.exceptions import TypeMismatch


def test_test_bytes(get_contract_with_gas_estimation, tx_failed):
    test_bytes = """
@external
def foo(x: Bytes[100]) -> Bytes[100]:
    return x
    """

    c = get_contract_with_gas_estimation(test_bytes)
    moo_result = c.foo(b"cow")
    assert moo_result == b"cow"

    print("Passed basic bytes test")

    assert c.foo(b"\x35" * 100) == b"\x35" * 100

    print("Passed max-length bytes test")

    # test for greater than 100 bytes, should raise exception
    with tx_failed():
        c.foo(b"\x35" * 101)

    print("Passed input-too-long test")


def test_test_bytes2(get_contract_with_gas_estimation):
    test_bytes2 = """
@external
def foo(x: Bytes[100]) -> Bytes[100]:
    y: Bytes[100] = x
    return y
    """

    c = get_contract_with_gas_estimation(test_bytes2)
    assert c.foo(b"cow") == b"cow"
    assert c.foo(b"") == b""
    assert c.foo(b"\x35" * 63) == b"\x35" * 63
    assert c.foo(b"\x35" * 64) == b"\x35" * 64
    assert c.foo(b"\x35" * 65) == b"\x35" * 65

    print("Passed string copying test")


def test_test_bytes3(get_contract_with_gas_estimation):
    test_bytes3 = """
x: int128
maa: Bytes[60]
y: int128

@deploy
def __init__():
    self.x = 27
    self.y = 37

@external
def set_maa(inp: Bytes[60]):
    self.maa = inp

@external
def set_maa2(inp: Bytes[60]):
    ay: Bytes[60] = inp
    self.maa = ay

@external
def get_maa() -> Bytes[60]:
    return self.maa

@external
def get_maa2() -> Bytes[60]:
    ay: Bytes[60] = self.maa
    return ay

@external
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

    print("Passed advanced string copying test")


def test_test_bytes4(get_contract_with_gas_estimation):
    test_bytes4 = """
a: Bytes[60]
@external
def foo(inp: Bytes[60]) -> Bytes[60]:
    self.a = inp
    self.a = b""
    return self.a

@external
def bar(inp: Bytes[60]) -> Bytes[60]:
    b: Bytes[60] = inp
    b = b""
    return b
    """

    c = get_contract_with_gas_estimation(test_bytes4)
    assert c.foo(b"") == b"", c.foo()
    assert c.bar(b"") == b""

    print("Passed string deleting test")


def test_test_bytes5(get_contract_with_gas_estimation):
    test_bytes5 = """
struct G:
    a: Bytes[50]
    b: Bytes[50]
struct H:
    a: Bytes[40]
    b: Bytes[45]

g: G

@external
def foo(inp1: Bytes[40], inp2: Bytes[45]):
    self.g = G(a=inp1, b=inp2)

@external
def check1() -> Bytes[50]:
    return self.g.a

@external
def check2() -> Bytes[50]:
    return self.g.b

@external
def bar(inp1: Bytes[40], inp2: Bytes[45]) -> Bytes[50]:
    h: H = H(a=inp1, b=inp2)
    return h.a

@external
def bat(inp1: Bytes[40], inp2: Bytes[45]) -> Bytes[50]:
    h: H = H(a=inp1, b=inp2)
    return h.b

@external
def quz(inp1: Bytes[40], inp2: Bytes[45]):
    h:  H = H(a=inp1, b=inp2)
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

    print("Passed string struct test")


def test_binary_literal(get_contract_with_gas_estimation):
    bytes_to_num_code = """
r: Bytes[1]

@external
def get(a: Bytes[1]) -> Bytes[2]:
    return concat(a, 0b00000001)

@external
def getsome() -> Bytes[1]:
    return 0b00001110

@external
def testsome(a: Bytes[1]) -> bool:
    return a == 0b01100001

@external
def testsome_storage(y: Bytes[1]) -> bool:
    self.r = 0b01100001
    return self.r == y
    """

    c = get_contract_with_gas_estimation(bytes_to_num_code)

    assert c.getsome() == b"\x0e"
    assert c.testsome(b"a")
    assert c.testsome(b"\x61")
    assert c.testsome(0b1100001.to_bytes(1, "big"))
    assert not c.testsome(b"b")
    assert c.testsome_storage(b"a")
    assert not c.testsome_storage(b"x")


def test_bytes_comparison(get_contract_with_gas_estimation):
    code = """
@external
def get_mismatch(a: Bytes[1]) -> bool:
    b: Bytes[2] = b'ab'
    return a == b

@external
def get_large(a: Bytes[100]) -> bool:
    b: Bytes[100] = b'ab'
    return a == b
    """

    c = get_contract_with_gas_estimation(code)
    assert c.get_mismatch(b"\x00") is False
    assert c.get_large(b"\x00") is False
    assert c.get_large(b"ab") is True


def test_bytes32_literals(get_contract):
    code = """
@external
def test() -> bool:
    l: bytes32 = 0x0000000000000000000000000000000000000000000000000000000080ac58cd
    return l == 0x0000000000000000000000000000000000000000000000000000000080ac58cd

    """

    c = get_contract(code)

    assert c.test() is True


@pytest.mark.parametrize("m,val", [(2, b"ab"), (3, b"ab"), (3, b"abc")])
def test_bytes_literals(get_contract, m, val):
    vyper_literal = "0x" + val.ljust(m, b"\x00").hex()
    code = f"""
@external
def test() -> bool:
    l: bytes{m} = {vyper_literal}
    return l == {vyper_literal}

@external
def test2(l: bytes{m} = {vyper_literal}) -> bool:
    return l == {vyper_literal}
    """

    c = get_contract(code)

    assert c.test() is True
    assert c.test2() is True
    assert c.test2(vyper_literal) is True


def test_zero_padding_with_private(get_contract):
    code = """
counter: uint256

@internal
@view
def to_little_endian_64(_value: uint256) -> Bytes[8]:
    y: uint256 = 0
    x: uint256 = _value
    for _: uint256 in range(8):
        y = (y << 8) | (x & 255)
        x >>= 8
    return slice(convert(y, bytes32), 24, 8)

@external
def set_count(i: uint256):
    self.counter = i

@external
@view
def get_count() -> Bytes[24]:
    return self.to_little_endian_64(self.counter)
    """

    c = get_contract(code)

    assert c.get_count() == b"\x00\x00\x00\x00\x00\x00\x00\x00"
    c.set_count(1, transact={})
    assert c.get_count() == b"\x01\x00\x00\x00\x00\x00\x00\x00"
    c.set_count(0xF0F0F0, transact={})
    assert c.get_count() == b"\xf0\xf0\xf0\x00\x00\x00\x00\x00"
    c.set_count(0x0101010101010101, transact={})
    assert c.get_count() == b"\x01\x01\x01\x01\x01\x01\x01\x01"


cases_invalid_assignments = [
    (
        """
@external
def assign():
    xs: Bytes[32] = b"abcdef"
    y: bytes32 = xs
    """,
        TypeMismatch,
    ),
    (
        """
@external
def assign():
    xs: bytes6 = b"abcdef"
    """,
        TypeMismatch,
    ),
    (
        """
@external
def assign():
    xs: bytes4 = 0xabcdef  # bytes3 literal
    """,
        TypeMismatch,
    ),
    (
        """
@external
def assign():
    xs: bytes4 = 0x1234abcdef # bytes5 literal
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("code,exc", cases_invalid_assignments)
def test_invalid_assignments(get_contract, assert_compile_failed, code, exc):
    assert_compile_failed(lambda: get_contract(code), exc)
