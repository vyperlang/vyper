
def test_string_return(get_contract_with_gas_estimation):
    code = """
@public
def testb() -> string[100]:
    a: string[100] = "test return"
    return a

@public
def testa(inp: string[100]) -> string[100]:
    return inp
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testa('meh') == "meh"
    assert c.testb() == "test return"


def test_string_concat(get_contract_with_gas_estimation):
    code = """
@public
def testb(inp: string[10]) -> string[128]:
    a: string[100] = "return message:"
    a = concat(a, " ", inp)
    return a

@public
def testa(inp: string[10]) -> string[160]:
    a: string[100] = "<-- return message"
    return concat("Funny ", inp, " ", inp, a)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.testb('bob') == "return message: bob"
    assert c.testa('foo') == "Funny foo foo<-- return message"


def test_basic_long_string_as_keys(get_contract, w3):
    code = """
mapped_string: map(string[34], int128)

@public
def set(k: string[34], v: int128):
    self.mapped_string[k] = v

@public
def get(k: string[34]) -> int128:
    return self.mapped_string[k]
    """

    c = get_contract(code)

    c.set(b"a" * 34, 6789, transact={'gas': 10**6})

    assert c.get(b"a" * 34) == 6789


def test_string_slice(get_contract_with_gas_estimation, assert_tx_failed):
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
