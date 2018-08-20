def test_private_test(get_contract_with_gas_estimation):
    private_test_code = """
@private
def a() -> int128:
    return 5

@public
def returnten() -> int128:
    return self.a() * 2
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.returnten() == 10


def test_private_with_more_vars(get_contract):
    private_test_code = """
@private
def afunc() -> int128:
    a: int128 = 4
    b: int128 = 40
    c: int128 = 400
    return a + b + c


@public
def return_it() -> int128:
    a: int128 = 111
    b: int128 = 222
    c: int128 = self.afunc()
    assert a == 111
    assert b == 222
    assert c == 444
    return a + b + c
    """

    c = get_contract(private_test_code)
    assert c.return_it() == 777


def test_private_with_more_vars_nested(get_contract_with_gas_estimation):
    private_test_code = """
@private
def more() -> int128:
    a: int128 = 50
    b: int128 = 50
    c: int128 = 11
    return a + b + c

@private
def afunc() -> int128:
    a: int128 = 444
    a += self.more()
    assert a == 555
    return  a + self.more()

@public
def return_it() -> int128:
    a: int128 = 222
    b: int128 = 111
    c: int128 = self.afunc()
    assert a == 222
    assert b == 111
    return a + b + c
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.return_it() == 999


def test_private_with_args(get_contract_with_gas_estimation):
    private_test_code = """
@private
def add_times2(a: uint256, b: uint256) -> uint256:
    return 2 * (a + b)

@public
def return_it() -> uint256:
    a: uint256 = 111
    b: uint256 = 222
    c: uint256 = self.add_times2(100, 11)
    return a + b + c
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.return_it() == 555


def test_private_with_args_nested(get_contract_with_gas_estimation):
    private_test_code = """
@private
def multiply(a: uint256, b: uint256) -> uint256:
    c: uint256 = 7
    d: uint256 = 8
    e: uint256 = 9
    return a * b

@private
def add_times2(a: uint256, b: uint256) -> uint256:
    return self.multiply(3, (a + b))

@public
def return_it() -> uint256:
    a: uint256 = 111
    b: uint256 = 222
    c: uint256 = self.add_times2(0, a)
    return a + b + c
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.return_it() == 666


def test_private_bytes(get_contract_with_gas_estimation):
    private_test_code = """
greeting: public(bytes[100])

@public
def __init__():
    self.greeting = "Hello "

@private
def construct(greet: bytes[100]) -> bytes[200]:
    return concat(self.greeting, greet)

@public
def hithere(name: bytes[100]) -> bytes[200]:
    d: bytes[200] = self.construct(name)
    return d
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.hithere(b"bob") == b"Hello bob"
    assert c.hithere(b"alice") == b"Hello alice"


def test_private_statement(get_contract_with_gas_estimation):
    private_test_code = """
greeting: public(bytes[20])

@public
def __init__():
    self.greeting = "Hello "

@private
def set_greeting(_greeting: bytes[20]):
    a: uint256 = 333
    b: uint256 = 334
    c: uint256 = 335
    d: uint256 = 336
    if a + b + c + d == 1338:
        self.greeting = _greeting

@public
def construct(greet: bytes[20]) -> bytes[40]:
    return concat(self.greeting, greet)

@public
def iprefer(_greeting: bytes[20]):
    a: uint256 = 112
    b: uint256 = 211
    self.set_greeting(_greeting)
    assert a == 112
    assert b == 211

@public
def hithere(name: bytes[20]) -> bytes[40]:
    d: bytes[40] = self.construct(name)
    return d
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.hithere(b"Bob") == b"Hello Bob"
    c.iprefer(b'Hi there, ', transact={})
    assert c.hithere(b"Alice") == b"Hi there, Alice"
