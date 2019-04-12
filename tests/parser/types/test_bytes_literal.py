def test_bytes_literal_code(get_contract_with_gas_estimation):
    bytes_literal_code = """
@public
def foo() -> bytes[5]:
    return b"horse"

@public
def bar() -> bytes[10]:
    return concat(b"b", b"a", b"d", b"m", b"i", b"", b"nton")

@public
def baz() -> bytes[40]:
    return concat(b"0123456789012345678901234567890", b"12")

@public
def baz2() -> bytes[40]:
    return concat(b"01234567890123456789012345678901", b"12")

@public
def baz3() -> bytes[40]:
    return concat(b"0123456789012345678901234567890", b"1")

@public
def baz4() -> bytes[100]:
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


def test_bytes_literal_splicing_fuzz(get_contract_with_gas_estimation):
    for i in range(95, 96, 97):
        kode = """
moo: bytes[100]

@public
def foo(s: int128, L: int128) -> bytes[100]:
        x: int128 = 27
        r: bytes[100] = slice(b"%s", start=s, len=L)
        y: int128 = 37
        if x * y == 999:
            return r
        return b"3434346667777"

@public
def bar(s: int128, L: int128) -> bytes[100]:
        self.moo = b"%s"
        x: int128 = 27
        r: bytes[100] = slice(self.moo, start=s, len=L)
        y: int128  = 37
        if x * y == 999:
            return r
        return b"3434346667777"

@public
def baz(s: int128, L: int128) -> bytes[100]:
        x: int128 = 27
        self.moo = slice(b"%s", start=s, len=L)
        y: int128 = 37
        if x * y == 999:
            return self.moo
        return b"3434346667777"
        """ % (("c" * i), ("c" * i), ("c" * i))

        c = get_contract_with_gas_estimation(kode)
        for e in range(63, 64, 65):
            for _s in range(31, 32, 33):
                o1 = c.foo(_s, e - _s)
                o2 = c.bar(_s, e - _s)
                o3 = c.baz(_s, e - _s)
                assert o1 == o2 == o3 == b"c" * (e - _s), (i, _s, e - _s, o1, o2, o3)

    print("Passed string literal splicing fuzz-test")
