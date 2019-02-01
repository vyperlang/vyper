
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
def foo(inp: string[10], start: int128, _len: int128) -> string[10]:
    return slice(inp, start=start, len=_len)
    """

    c = get_contract_with_gas_estimation(test_slice4)
    assert c.foo("badminton", 3, 3) == "min"
    assert c.foo("badminton", 0, 9) == "badminton"
    assert c.foo("badminton", 1, 8) == "adminton"
    assert c.foo("badminton", 1, 7) == "adminto"
    assert c.foo("badminton", 1, 0) == ""
    assert c.foo("badminton", 9, 0) == ""

    assert_tx_failed(lambda: c.foo("badminton", 0, 10))
    assert_tx_failed(lambda: c.foo("badminton", 1, 9))
    assert_tx_failed(lambda: c.foo("badminton", 9, 1))
    assert_tx_failed(lambda: c.foo("badminton", 10, 0))


def test_private_string(get_contract_with_gas_estimation):
    private_test_code = """
greeting: public(string[100])

@public
def __init__():
    self.greeting = "Hello "

@private
def construct(greet: string[100]) -> string[200]:
    return concat(self.greeting, greet)

@public
def hithere(name: string[100]) -> string[200]:
    d: string[200] = self.construct(name)
    return d
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.hithere("bob") == "Hello bob"
    assert c.hithere("alice") == "Hello alice"


def test_logging_extended_string(get_contract_with_gas_estimation, get_logs):
    code = """
MyLog: event({arg1: int128, arg2: string[64], arg3: int128})

@public
def foo():
    log.MyLog(667788, 'hellohellohellohellohellohellohellohellohello', 334455)
    """

    c = get_contract_with_gas_estimation(code)
    log = get_logs(c.foo(transact={}), c, 'MyLog')

    assert log[0].args.arg1 == 667788
    assert log[0].args.arg2 == "hello" * 9
    assert log[0].args.arg3 == 334455
