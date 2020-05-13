import pytest


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
    self.greeting = b"Hello "

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
    self.greeting = b"Hello "

@private
def set_greeting(_greeting: bytes[20]):
    a: uint256 = 332
    b: uint256 = 333
    c: uint256 = 334
    d: uint256 = 335
    if a + b + c + d + 3 == 1337:
        self.greeting = _greeting

@private
@constant
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
    a_before: uint256 = a
    b_before: uint256 = b
    c: int128 = 333
    d: uint256 = self.addition(a, b)
    assert c == 333
    assert a_before == a
    assert b_before == b

    return d
    """

    c = get_contract_with_gas_estimation(private_test_code)

    assert c.add_one(20) == 21
    assert c.added(10, 20) == 30


def test_private_return_bytes(get_contract_with_gas_estimation):
    code = """
a_message: bytes[50]

@private
def _test() -> (bytes[100]):
    b: bytes[50] = b"hello                   1           2"
    return b

@private
def _test_b(a: bytes[100]) -> (bytes[100]):
    b: bytes[50] = b"hello there"
    if len(a) > 1:
        return a
    else:
        return b

@private
def get_msg() -> (bytes[100]):
    return self.a_message

@public
def test() -> (bytes[100]):
    d: bytes[100] = b""
    d = self._test()
    return d

@public
def test2() -> (bytes[100]):
    d: bytes[100] = b'xyzxyzxyzxyz'
    return self._test()

@public
def test3(a: bytes[50]) -> (bytes[100]):
    d: bytes[100] = b'xyzxyzxyzxyz'
    return self._test_b(a)

@public
def set(a: bytes[50]):
    self.a_message = a

@public
def test4() -> (bytes[100]):
    d: bytes[100] = b'xyzxyzxyzxyz'
    return self.get_msg()
    """

    c = get_contract_with_gas_estimation(code)
    test_str = b"                   1           2"
    assert c.test() == b"hello" + test_str
    assert c.test2() == b"hello" + test_str
    assert c.test3(b"alice") == b"alice"
    c.set(b"hello daar", transact={})
    assert c.test4() == b"hello daar"


def test_private_bytes_as_args(get_contract_with_gas_estimation):
    code = """
@private
def _test(a: bytes[40]) -> (bytes[100]):
    b: bytes[40] = b"hello "
    return concat(b, a)

@public
def test(a: bytes[10]) -> bytes[100]:
    b: bytes[40] = concat(a, b", jack attack")
    out: bytes[100] = self._test(b)
    return out

@public
def test2() -> bytes[100]:
    c: bytes[10] = b"alice"
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
    f: bytes32 = EMPTY_BYTES32
    f, b, c = self._test(a)
    assert d == 123
    return f, b, c

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
    return a + 2, concat(b"badabing:", b)

@private
def _test_combined(a: bytes[50], x: int128, c:bytes[50]) -> (int128, bytes[100], bytes[100]):
    assert x == 8
    return x + 2, a, concat(c, b'_two')

@public
def test(a: int128, b: bytes[40]) -> (int128, bytes[100], bytes[50]):
    c: int128 = 1
    x: bytes[50] = concat(b, b"_one")
    d: bytes[100] = b""
    c, d = self._test(a + c, x)
    return c, d, x

@public
def test2(b: bytes[40]) -> (int128, bytes[100]):
    a: int128 = 4
    x: bytes[50] = concat(b, b"_one")
    d: bytes[100] = b""
    return self._test(a, x)

@public
def test3(a: bytes[32]) -> (int128, bytes[100], bytes[100]):
    q: bytes[100] = b"random data1"
    w: bytes[100] = b"random data2"
    x: int128 = 8
    b: bytes[32] = a
    x, q, w = self._test_combined(a, x, b)
    return x, q, w

@public
def test4(a: bytes[40]) -> (int128, bytes[100], bytes[100]):
    b: bytes[50] = concat(a, b"_one")
    return self._test_combined(a, 8, b)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test(11, b"jill") == [14, b'badabing:jill_one', b'jill_one']
    assert c.test2(b"jack") == [6, b'badabing:jack_one']
    assert c.test3(b"hill") == [10, b'hill', b'hill_two']
    assert c.test4(b"bucket") == [10, b'bucket', b'bucket_one_two']


def test_private_return_list_types(get_contract_with_gas_estimation):
    code = """
@private
def _test(b: int128[4]) -> int128[4]:
    assert b[1] == 2
    assert b[2] == 3
    assert b[3] == 4
    return [0, 1, 0, 1]

@public
def test() -> int128[4]:
    b: int128[4] = [1, 2, 3, 4]
    c: int128[2] = [11, 22]
    return self._test(b)
    """
    c = get_contract_with_gas_estimation(code)

    assert c.test() == [0, 1, 0, 1]


def test_private_payable(w3, get_contract_with_gas_estimation):
    code = """
@private
def _send_it(a: address, _value: uint256):
    send(a, _value)

@payable
@public
def test(doit: bool, a: address, _value: uint256):
    self._send_it(a, _value)

@public
@payable
def __default__():
    pass
    """

    c = get_contract_with_gas_estimation(code)

    w3.eth.sendTransaction({'to': c.address, 'value': w3.toWei(1, 'ether')})
    assert w3.eth.getBalance(c.address) == w3.toWei(1, 'ether')
    a3 = w3.eth.accounts[2]
    assert w3.eth.getBalance(a3) == w3.toWei(1000000, 'ether')
    c.test(True, a3, w3.toWei(0.05, 'ether'), transact={})
    assert w3.eth.getBalance(a3) == w3.toWei(1000000.05, 'ether')
    assert w3.eth.getBalance(c.address) == w3.toWei(0.95, 'ether')


def test_private_msg_sender(get_contract, assert_compile_failed):
    code = """
@private
def _whoami() -> address:
    return msg.sender
    """

    assert_compile_failed(lambda: get_contract(code))


def test_nested_static_params_only(get_contract, assert_tx_failed):
    code1 = """
@private
@constant
def c() -> bool:
    return True

@private
@constant
def b(sender: address) -> address:
    assert self.c()
    return sender

@public
def a() -> bool:
    assert self.b(msg.sender) == msg.sender
    return True
    """

    code2 = """
@private
@constant
def c(sender: address) -> address:
    return sender

@private
@constant
def b(sender: address) -> address:
    return self.c(sender)

@public
def a() -> bool:
    assert self.b(msg.sender) == msg.sender
    return True
    """

    c1 = get_contract(code1)
    c2 = get_contract(code2)
    assert c1.a() is True
    assert c2.a() is True


def test_private_nested_if_return(get_contract):
    code = """

@private
def _test(z: int128) -> bool:
    y: int128 = 1

    if (z <= 0):
        return True
    else:
        y = 2

    return False


@public
def test(z: int128) -> bool:
    return self._test(z)
    """

    c = get_contract(code)

    assert c.test(-1) is True
    assert c.test(0) is True
    assert c.test(1) is False


def test_private_call_expr(get_contract):
    code = """
test: public(bool)


@private
def foo():
    self.test = True


@public
def start():
    if True:
        self.foo()
    """

    c = get_contract(code)

    assert c.test() is False
    c.start(transact={})
    assert c.test() is True


def test_private_array_param(get_contract):
    code = """
@private
def change_arr(arr: int128[2]):
    pass
@public
def call_arr() -> int128:
    a: int128[2] = [0, 0] # test with zeroed arg
    self.change_arr(a)
    return 42
    """

    c = get_contract(code)
    assert c.call_arr() == 42


def test_private_zero_bytearray(get_contract):
    private_test_code = """
@private
def inner(xs: bytes[256]):
    pass
@public
def outer(xs: bytes[256] = b"") -> bool:
    self.inner(xs)
    return True
    """

    c = get_contract(private_test_code)
    assert c.outer()


tuple_return_sources = [
    ("""
@private
def _test(a: int128) -> (int128, int128):
    return a + 2, 2


@public
def foo(a: int128) -> (int128, int128):
    return self._test(a)
    """, (11,), [13, 2]),
    ("""
struct A:
    many: uint256[4]
    one: uint256

@private
def _foo(_many: uint256[4], _one: uint256) -> A:
    return A({many: _many, one: _one})

@public
def foo() -> A:
    return self._foo([1, 2, 3, 4], 5)
    """, (), ([1, 2, 3, 4], 5)),
    ("""
struct A:
    many: uint256[4]
    one: uint256

@private
def _foo(_many: uint256[4], _one: uint256) -> A:
    return A({many: _many, one: _one})

@public
def foo() -> (uint256[4], uint256):
    out: A = self._foo([1, 2, 3, 4], 5)
    return out.many, out.one
    """, (), [[1, 2, 3, 4], 5]),
    ("""
@private
def _foo() -> (uint256[2], uint256[2]):
    return [1, 2], [5, 6]

@public
def foo() -> (uint256[2], uint256[2], uint256[2]):
    return self._foo()[0], [3, 4], self._foo()[1]
    """, (), [[1, 2], [3, 4], [5, 6]]),
    ("""
@private
def _foo(a: int128, b: int128[3], c: int128[3]) -> (int128[3], int128, int128[3]):
    return c, 4, [b[1], a, b[0]]

@public
def foo(a: int128, b: int128[3], c: int128[3]) -> (int128[3], int128, int128[3]):
    return self._foo(a, b, c)
    """, (6, [7, 5, 8], [1, 2, 3]), [[1, 2, 3], 4, [5, 6, 7]]),
    ("""
@private
def _foo(a: int128, b: int128[3], c: int128[3]) -> (int128[3], int128, int128[3]):
    return c, 4, [b[1], a, b[0]]

@public
def foo(a: int128, b: int128[3], c: int128[3]) -> (int128[3], int128, int128[3]):
    return c, 4, self._foo(a, b, c)[2]
    """, (6, [7, 5, 8], [1, 2, 3]), [[1, 2, 3], 4, [5, 6, 7]]),

]


@pytest.mark.parametrize("source_code,args,expected", tuple_return_sources)
def test_tuple_return_types(get_contract, source_code, args, expected):
    c = get_contract(source_code)

    assert c.foo(*args) == expected
