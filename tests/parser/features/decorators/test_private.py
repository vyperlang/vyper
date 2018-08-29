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
    assert a == 100
    assert b == 11
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
    assert c.greeting() == b"Hello "
    assert c.hithere(b"Bob") == b"Hello Bob"
    c.iprefer(b'Hi there, ', transact={})
    assert c.hithere(b"Alice") == b"Hi there, Alice"


def test_private_default_parameter(get_contract_with_gas_estimation):
    private_test_code = """
@private
def addition(a: uint256, b: uint256 = 1) -> uint256:
    return a + b


@public
def add_one(a: uint256) -> uint256:
    return self.addition(a)

@public
def added(a: uint256, b: uint256) -> uint256:
    c: int128 = 333
    d: uint256 = self.addition(a, b)
    assert c == 333

    return d
    """

    c = get_contract_with_gas_estimation(private_test_code)

    assert c.add_one(20) == 21
    assert c.added(10, 20) == 30


def test_private_return_tuple(get_contract_with_gas_estimation):
    code = """
@private
# @public
def _test(a: int128) -> (int128, int128):
    return a + 2, 2


@public
def test(a: int128) -> (int128, int128):
    return self._test(a)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test(11) == [13, 2]


def test_private_return_bytes(get_contract_with_gas_estimation):
    code = """
a_message: bytes[50]

@private
def _test() -> (bytes[100]):
    b: bytes[50] = "hello                   1           2"
    return b

@private
def _test_b(a: bytes[100]) -> (bytes[100]):
    b: bytes[50] = "hello there"
    if len(a) > 1:
        return a
    else:
        return b

@private
def get_msg() -> (bytes[100]):
    return self.a_message

@public
def test() -> (bytes[100]):
    d: bytes[100]
    d = self._test()
    return d

@public
def test2() -> (bytes[100]):
    d: bytes[100] = 'xyzxyzxyzxyz'
    return self._test()

@public
def test3(a: bytes[50]) -> (bytes[100]):
    d: bytes[100] = 'xyzxyzxyzxyz'
    return self._test_b(a)

@public
def set(a: bytes[50]):
    self.a_message = a

@public
def test4() -> (bytes[100]):
    d: bytes[100] = 'xyzxyzxyzxyz'
    return self.get_msg()
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test() == b"hello                   1           2"
    assert c.test2() == b"hello                   1           2"
    assert c.test3(b"alice") == b"alice"
    c.set(b"hello daar", transact={})
    assert c.test4() == b"hello daar"


def test_private_bytes_as_args(get_contract_with_gas_estimation):
    code = """
@private
def _test(a: bytes[40]) -> (bytes[100]):
    b: bytes[40] = "hello "
    return concat(b, a)

@public
def test(a: bytes[10]) -> bytes[100]:
    b: bytes[40] = concat(a, ", jack attack")
    out: bytes[100] = self._test(b)
    return out

@public
def test2() -> bytes[100]:
    c: bytes[10] = "alice"
    return self._test(c)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.test(b"bob") == b"hello bob, jack attack"
    assert c.test2() == b"hello alice"


def test_private_return_tuple_base_types(get_contract_with_gas_estimation):
    code = """
@private
def _test(a: bytes32) -> (bytes32, uint256, int128):
    b: uint256 = 1000
    return a, b, -1200

@public
def test(a: bytes32) -> (bytes32, uint256, int128):
    b: uint256 = 1
    c: int128 = 1
    d: int128 = 123
    a, b, c = self._test(a)
    assert d == 123
    return a, b, c

@public
def test2(a: bytes32) -> (bytes32, uint256, int128):
    return self._test(a)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test(b"test") == [b"test" + 28 * b'\x00', 1000, -1200]
    assert c.test2(b"test") == [b"test" + 28 * b'\x00', 1000, -1200]


def test_private_return_tuple_bytes(get_contract_with_gas_estimation):
    code = """
@private
def _test(a: int128, b: bytes[50]) -> (int128, bytes[100]):
    return a + 2, concat("badabing:", b)

@public
def test(a: int128, b: bytes[50]) -> (int128, bytes[100], bytes[50]):
    c: int128
    d: bytes[100]
    c, d = self._test(a, b)
    return c, d, b
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test(11, b"test") == [13, b"badabing:test", b"test"]

# Return types to test:
# 1.) ListType
# 3.) Straight tuple return `return self.priv_call() -> (int128, bytes[10]`
