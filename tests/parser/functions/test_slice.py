

def test_test_slice(get_contract_with_gas_estimation):
    test_slice = """

@public
def foo(inp1: bytes[10]) -> bytes[3]:
    x: int128 = 5
    s: bytes[3] = slice(inp1, start=3, len=3)
    y: int128 = 7
    return s

@public
def bar(inp1: bytes[10]) -> int128:
    x: int128 = 5
    s: bytes[3] = slice(inp1, start=3, len=3)
    y: int128 = 7
    return x * y
    """

    c = get_contract_with_gas_estimation(test_slice)
    x = c.foo(b"badminton")
    assert x == b"min", x

    assert c.bar(b"badminton") == 35

    print('Passed slice test')


def test_test_slice2(get_contract_with_gas_estimation):
    test_slice2 = """
@public
def slice_tower_test(inp1: bytes[50]) -> bytes[50]:
    inp: bytes[50] = inp1
    for i in range(1, 11):
        inp = slice(inp, start=1, len=30 - i * 2)
    return inp
    """
    c = get_contract_with_gas_estimation(test_slice2)
    x = c.slice_tower_test(b"abcdefghijklmnopqrstuvwxyz1234")
    assert x == b"klmnopqrst", x

    print('Passed advanced slice test')


def test_test_slice3(get_contract_with_gas_estimation):
    test_slice3 = """
x: int128
s: bytes[50]
y: int128
@public
def foo(inp1: bytes[50]) -> bytes[50]:
    self.x = 5
    self.s = slice(inp1, start=3, len=3)
    self.y = 7
    return self.s

@public
def bar(inp1: bytes[50]) -> int128:
    self.x = 5
    self.s = slice(inp1, start=3, len=3)
    self.y = 7
    return self.x * self.y
    """

    c = get_contract_with_gas_estimation(test_slice3)
    x = c.foo(b"badminton")
    assert x == b"min", x

    assert c.bar(b"badminton") == 35

    print('Passed storage slice test')


def test_test_slice4(get_contract_with_gas_estimation, assert_tx_failed):
    test_slice4 = """
@public
def foo(inp: bytes[10], start: int128, _len: int128) -> bytes[10]:
    return slice(inp, start=start, len=_len)
    """

    c = get_contract_with_gas_estimation(test_slice4)
    assert c.foo(b"badminton", 3, 3) == b"min"
    assert c.foo(b"badminton", 0, 9) == b"badminton"
    assert c.foo(b"badminton", 1, 8) == b"adminton"
    assert c.foo(b"badminton", 1, 7) == b"adminto"
    assert c.foo(b"badminton", 1, 0) == b""
    assert c.foo(b"badminton", 9, 0) == b""

    assert_tx_failed(lambda: c.foo(b"badminton", 0, 10))
    assert_tx_failed(lambda: c.foo(b"badminton", 1, 9))
    assert_tx_failed(lambda: c.foo(b"badminton", 9, 1))
    assert_tx_failed(lambda: c.foo(b"badminton", 10, 0))

    print('Passed slice edge case test')


def test_slice_at_end(get_contract):
    code = """
@public
def ret10_slice() -> bytes[10]:
    b: bytes[32] = concat(convert(65, 'bytes32'), '')
    c: bytes[10] = slice(b, start=31, len=1)
    return c
    """

    c = get_contract(code)
    assert c.ret10_slice() == b'A'
