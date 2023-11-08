import itertools

import pytest


def test_bytes_literal_code(get_contract_with_gas_estimation):
    bytes_literal_code = """
@external
def foo() -> Bytes[5]:
    return b"horse"

@external
def bar() -> Bytes[10]:
    return concat(b"b", b"a", b"d", b"m", b"i", b"", b"nton")

@external
def baz() -> Bytes[40]:
    return concat(b"0123456789012345678901234567890", b"12")

@external
def baz2() -> Bytes[40]:
    return concat(b"01234567890123456789012345678901", b"12")

@external
def baz3() -> Bytes[40]:
    return concat(b"0123456789012345678901234567890", b"1")

@external
def baz4() -> Bytes[100]:
    return concat(b"01234567890123456789012345678901234567890123456789",
                  b"01234567890123456789012345678901234567890123456789")
    """

    c = get_contract_with_gas_estimation(bytes_literal_code)
    assert c.foo() == b"horse"
    assert c.bar() == b"badminton"
    assert c.baz() == b"012345678901234567890123456789012"
    assert c.baz2() == b"0123456789012345678901234567890112"
    assert c.baz3() == b"01234567890123456789012345678901"
    assert c.baz4() == b"0123456789" * 10

    print("Passed string literal test")


@pytest.mark.parametrize("i,e,_s", itertools.product([95, 96, 97], [63, 64, 65], [31, 32, 33]))
def test_bytes_literal_splicing_fuzz(get_contract_with_gas_estimation, i, e, _s):
    kode = f"""
moo: Bytes[100]

@external
def foo(s: uint256, L: uint256) -> Bytes[100]:
    x: int128 = 27
    r: Bytes[100] = slice(b"{("c" * i)}", s, L)
    y: int128 = 37
    if x * y == 999:
        return r
    return b"3434346667777"

@external
def bar(s: uint256, L: uint256) -> Bytes[100]:
    self.moo = b"{("c" * i)}"
    x: int128 = 27
    r: Bytes[100] = slice(self.moo, s, L)
    y: int128  = 37
    if x * y == 999:
        return r
    return b"3434346667777"

@external
def baz(s: uint256, L: uint256) -> Bytes[100]:
    x: int128 = 27
    self.moo = slice(b"{("c" * i)}", s, L)
    y: int128 = 37
    if x * y == 999:
        return self.moo
    return b"3434346667777"
    """

    c = get_contract_with_gas_estimation(kode)
    o1 = c.foo(_s, e - _s)
    o2 = c.bar(_s, e - _s)
    o3 = c.baz(_s, e - _s)
    assert o1 == o2 == o3 == b"c" * (e - _s), (i, _s, e - _s, o1, o2, o3)

    print("Passed string literal splicing fuzz-test")
