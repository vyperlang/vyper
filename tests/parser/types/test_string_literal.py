def test_string_literal_code(get_contract_with_gas_estimation):
    string_literal_code = """
@public
def foo() -> bytes <= 5:
    return "horse"

@public
def bar() -> bytes <= 10:
    return concat("b", "a", "d", "m", "i", "", "nton")

@public
def baz() -> bytes <= 40:
    return concat("0123456789012345678901234567890", "12")

@public
def baz2() -> bytes <= 40:
    return concat("01234567890123456789012345678901", "12")

@public
def baz3() -> bytes <= 40:
    return concat("0123456789012345678901234567890", "1")

@public
def baz4() -> bytes <= 100:
    return concat("01234567890123456789012345678901234567890123456789",
                  "01234567890123456789012345678901234567890123456789")
    """

    c = get_contract_with_gas_estimation(string_literal_code)
    assert c.foo() == b"horse"
    assert c.bar() == b"badminton"
    assert c.baz() == b"012345678901234567890123456789012"
    assert c.baz2() == b"0123456789012345678901234567890112"
    assert c.baz3() == b"01234567890123456789012345678901"
    assert c.baz4() == b"0123456789" * 10

    print("Passed string literal test")


def test_string_literal_splicing_fuzz(get_contract_with_gas_estimation):
    for i in range(95, 96, 97):
        kode = """
moo: bytes <= 100

@public
def foo(s: num, L: num) -> bytes <= 100:
        x: num = 27
        r: bytes <= 100 = slice("%s", start=s, len=L)
        y: num = 37
        if x * y == 999:
            return r

@public
def bar(s: num, L: num) -> bytes <= 100:
        self.moo = "%s"
        x: num = 27
        r: bytes <= 100 = slice(self.moo, start=s, len=L)
        y: num  = 37
        if x * y == 999:
            return r

@public
def baz(s: num, L: num) -> bytes <= 100:
        x: num = 27
        self.moo = slice("%s", start=s, len=L)
        y: num = 37
        if x * y == 999:
            return self.moo
        """ % (("c" * i), ("c" * i), ("c" * i))
        c = get_contract_with_gas_estimation(kode)
        for e in range(63, 64, 65):
            for _s in range(31, 32, 33):
                o1 = c.foo(_s, e - _s)
                o2 = c.bar(_s, e - _s)
                o3 = c.baz(_s, e - _s)
                assert o1 == o2 == o3 == b"c" * (e - _s), (i, _s, e - _s, o1, o2, o3)

    print("Passed string literal splicing fuzz-test")
