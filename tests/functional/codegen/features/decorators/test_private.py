import pytest


def test_private_test(get_contract_with_gas_estimation):
    private_test_code = """
@internal
def a() -> int128:
    return 5

@external
def returnten() -> int128:
    return self.a() * 2
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.returnten() == 10


def test_private_with_more_vars(get_contract):
    private_test_code = """
@internal
def afunc() -> int128:
    a: int128 = 4
    b: int128 = 40
    c: int128 = 400
    return a + b + c


@external
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
@internal
def more() -> int128:
    a: int128 = 50
    b: int128 = 50
    c: int128 = 11
    return a + b + c

@internal
def afunc() -> int128:
    a: int128 = 444
    a += self.more()
    assert a == 555
    return  a + self.more()

@external
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
@internal
def add_times2(a: uint256, b: uint256) -> uint256:
    assert a == 100
    assert b == 11
    return 2 * (a + b)

@external
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
@internal
def multiply(a: uint256, b: uint256) -> uint256:
    c: uint256 = 7
    d: uint256 = 8
    e: uint256 = 9
    return a * b

@internal
def add_times2(a: uint256, b: uint256) -> uint256:
    return self.multiply(3, (a + b))

@external
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
greeting: public(Bytes[100])

@deploy
def __init__():
    self.greeting = b"Hello "

@internal
def construct(greet: Bytes[100]) -> Bytes[200]:
    return concat(self.greeting, greet)

@external
def hithere(name: Bytes[100]) -> Bytes[200]:
    d: Bytes[200] = self.construct(name)
    return d
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.hithere(b"bob") == b"Hello bob"
    assert c.hithere(b"alice") == b"Hello alice"


def test_private_statement(get_contract_with_gas_estimation):
    private_test_code = """
greeting: public(Bytes[20])

@deploy
def __init__():
    self.greeting = b"Hello "

@internal
def set_greeting(_greeting: Bytes[20]):
    a: uint256 = 332
    b: uint256 = 333
    c: uint256 = 334
    d: uint256 = 335
    if a + b + c + d + 3 == 1337:
        self.greeting = _greeting

@internal
@view
def construct(greet: Bytes[20]) -> Bytes[40]:
    return concat(self.greeting, greet)

@external
def iprefer(_greeting: Bytes[20]):
    a: uint256 = 112
    b: uint256 = 211
    self.set_greeting(_greeting)
    assert a == 112
    assert b == 211

@external
def hithere(name: Bytes[20]) -> Bytes[40]:
    d: Bytes[40] = self.construct(name)
    return d
    """

    c = get_contract_with_gas_estimation(private_test_code)
    assert c.greeting() == b"Hello "
    assert c.hithere(b"Bob") == b"Hello Bob"
    c.iprefer(b"Hi there, ", transact={})
    assert c.hithere(b"Alice") == b"Hi there, Alice"


def test_private_default_parameter(get_contract_with_gas_estimation):
    private_test_code = """
@internal
def addition(a: uint256, b: uint256 = 1) -> uint256:
    return a + b


@external
def add_one(a: uint256) -> uint256:
    return self.addition(a)

@external
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
a_message: Bytes[50]

@internal
def _test() -> (Bytes[100]):
    b: Bytes[50] = b"hello                   1           2"
    return b

@internal
def _test_b(a: Bytes[100]) -> (Bytes[100]):
    b: Bytes[50] = b"hello there"
    if len(a) > 1:
        return a
    else:
        return b

@internal
def get_msg() -> (Bytes[100]):
    return self.a_message

@external
def test() -> (Bytes[100]):
    d: Bytes[100] = b""
    d = self._test()
    return d

@external
def test2() -> (Bytes[100]):
    d: Bytes[100] = b'xyzxyzxyzxyz'
    return self._test()

@external
def test3(a: Bytes[50]) -> (Bytes[100]):
    d: Bytes[100] = b'xyzxyzxyzxyz'
    return self._test_b(a)

@external
def set(a: Bytes[50]):
    self.a_message = a

@external
def test4() -> (Bytes[100]):
    d: Bytes[100] = b'xyzxyzxyzxyz'
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
@internal
def _test(a: Bytes[40]) -> (Bytes[100]):
    b: Bytes[40] = b"hello "
    return concat(b, a)

@external
def test(a: Bytes[10]) -> Bytes[100]:
    b: Bytes[40] = concat(a, b", jack attack")
    out: Bytes[100] = self._test(b)
    return out

@external
def test2() -> Bytes[100]:
    c: Bytes[10] = b"alice"
    return self._test(c)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.test(b"bob") == b"hello bob, jack attack"
    assert c.test2() == b"hello alice"


def test_private_return_tuple_base_types(get_contract_with_gas_estimation):
    code = """
@internal
def _test(a: bytes32) -> (bytes32, uint256, int128):
    b: uint256 = 1000
    return a, b, -1200

@external
def test(a: bytes32) -> (bytes32, uint256, int128):
    b: uint256 = 1
    c: int128 = 1
    d: int128 = 123
    f: bytes32 = empty(bytes32)
    f, b, c = self._test(a)
    assert d == 123
    return f, b, c

@external
def test2(a: bytes32) -> (bytes32, uint256, int128):
    return self._test(a)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test(b"test" + b"\x00" * 28) == [b"test" + 28 * b"\x00", 1000, -1200]
    assert c.test2(b"test" + b"\x00" * 28) == [b"test" + 28 * b"\x00", 1000, -1200]


def test_private_return_tuple_bytes(get_contract_with_gas_estimation):
    code = """
@internal
def _test(a: int128, b: Bytes[50]) -> (int128, Bytes[100]):
    return a + 2, concat(b"badabing:", b)

@internal
def _test_combined(a: Bytes[50], x: int128, c:Bytes[50]) -> (int128, Bytes[100], Bytes[100]):
    assert x == 8
    return x + 2, a, concat(c, b'_two')

@external
def test(a: int128, b: Bytes[40]) -> (int128, Bytes[100], Bytes[50]):
    c: int128 = 1
    x: Bytes[50] = concat(b, b"_one")
    d: Bytes[100] = b""
    c, d = self._test(a + c, x)
    return c, d, x

@external
def test2(b: Bytes[40]) -> (int128, Bytes[100]):
    a: int128 = 4
    x: Bytes[50] = concat(b, b"_one")
    d: Bytes[100] = b""
    return self._test(a, x)

@external
def test3(a: Bytes[32]) -> (int128, Bytes[100], Bytes[100]):
    q: Bytes[100] = b"random data1"
    w: Bytes[100] = b"random data2"
    x: int128 = 8
    b: Bytes[32] = a
    x, q, w = self._test_combined(a, x, b)
    return x, q, w

@external
def test4(a: Bytes[40]) -> (int128, Bytes[100], Bytes[100]):
    b: Bytes[50] = concat(a, b"_one")
    return self._test_combined(a, 8, b)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test(11, b"jill") == [14, b"badabing:jill_one", b"jill_one"]
    assert c.test2(b"jack") == [6, b"badabing:jack_one"]
    assert c.test3(b"hill") == [10, b"hill", b"hill_two"]
    assert c.test4(b"bucket") == [10, b"bucket", b"bucket_one_two"]


def test_private_return_list_types(get_contract_with_gas_estimation):
    code = """
@internal
def _test(b: int128[4]) -> int128[4]:
    assert b[1] == 2
    assert b[2] == 3
    assert b[3] == 4
    return [0, 1, 0, 1]

@external
def test() -> int128[4]:
    b: int128[4] = [1, 2, 3, 4]
    c: int128[2] = [11, 22]
    return self._test(b)
    """
    c = get_contract_with_gas_estimation(code)

    assert c.test() == [0, 1, 0, 1]


def test_private_payable(w3, get_contract_with_gas_estimation):
    code = """
@internal
def _send_it(a: address, _value: uint256):
    send(a, _value)

@payable
@external
def test(doit: bool, a: address, _value: uint256):
    self._send_it(a, _value)

@external
@payable
def __default__():
    pass
    """

    c = get_contract_with_gas_estimation(code)

    w3.eth.send_transaction({"to": c.address, "value": w3.to_wei(1, "ether")})
    assert w3.eth.get_balance(c.address) == w3.to_wei(1, "ether")
    a3 = w3.eth.accounts[2]
    assert w3.eth.get_balance(a3) == w3.to_wei(1000000, "ether")
    c.test(True, a3, w3.to_wei(0.05, "ether"), transact={})
    assert w3.eth.get_balance(a3) == w3.to_wei(1000000.05, "ether")
    assert w3.eth.get_balance(c.address) == w3.to_wei(0.95, "ether")


def test_private_msg_sender(get_contract, w3):
    code = """
event Addr:
    addr: address

@internal
@view
def _whoami() -> address:
    return msg.sender

@external
@view
def i_am_me() -> bool:
    return msg.sender == self._whoami()

@external
@nonpayable
def whoami() -> address:
    log Addr(self._whoami())
    return self._whoami()
    """

    c = get_contract(code)
    assert c.i_am_me()

    addr = w3.eth.accounts[1]
    txhash = c.whoami(transact={"from": addr})
    receipt = w3.eth.wait_for_transaction_receipt(txhash)
    logged_addr = w3.to_checksum_address(receipt.logs[0].data[-20:])
    assert logged_addr == addr, "oh no"


def test_nested_static_params_only(get_contract, tx_failed):
    code1 = """
@internal
@view
def c() -> bool:
    return True

@internal
@view
def b(sender: address) -> address:
    assert self.c()
    return sender

@external
def a() -> bool:
    assert self.b(msg.sender) == msg.sender
    return True
    """

    code2 = """
@internal
@view
def c(sender: address) -> address:
    return sender

@internal
@view
def b(sender: address) -> address:
    return self.c(sender)

@external
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

@internal
def _test(z: int128) -> bool:
    y: int128 = 1

    if (z <= 0):
        return True
    else:
        y = 2

    return False


@external
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


@internal
def foo():
    self.test = True


@external
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
@internal
def change_arr(arr: int128[2]):
    pass
@external
def call_arr() -> int128:
    a: int128[2] = [0, 0] # test with zeroed arg
    self.change_arr(a)
    return 42
    """

    c = get_contract(code)
    assert c.call_arr() == 42


def test_private_zero_bytearray(get_contract):
    private_test_code = """
@internal
def inner(xs: Bytes[256]):
    pass
@external
def outer(xs: Bytes[256] = b"") -> bool:
    self.inner(xs)
    return True
    """

    c = get_contract(private_test_code)
    assert c.outer()


tuple_return_sources = [
    (
        """
@internal
def _test(a: int128) -> (int128, int128):
    return a + 2, 2


@external
def foo(a: int128) -> (int128, int128):
    return self._test(a)
    """,
        (11,),
        [13, 2],
    ),
    (
        """
struct A:
    one: uint8

@internal
def _foo(_one: uint8) ->A:
    return A(one=_one)

@external
def foo() -> A:
    return self._foo(1)
    """,
        (),
        (1,),
    ),
    (
        """
struct A:
    many: uint256[4]
    one: uint256

@internal
def _foo(_many: uint256[4], _one: uint256) -> A:
    return A(many=_many, one=_one)

@external
def foo() -> A:
    return self._foo([1, 2, 3, 4], 5)
    """,
        (),
        ([1, 2, 3, 4], 5),
    ),
    (
        """
struct A:
    many: uint256[4]
    one: uint256

@internal
def _foo(_many: uint256[4], _one: uint256) -> A:
    return A(many=_many, one=_one)

@external
def foo() -> (uint256[4], uint256):
    out: A = self._foo([1, 2, 3, 4], 5)
    return out.many, out.one
    """,
        (),
        [[1, 2, 3, 4], 5],
    ),
    (
        """
@internal
def _foo() -> (uint256[2], uint256[2]):
    return [1, 2], [5, 6]

@external
def foo() -> (uint256[2], uint256[2], uint256[2]):
    return self._foo()[0], [3, 4], self._foo()[1]
    """,
        (),
        [[1, 2], [3, 4], [5, 6]],
    ),
    (
        """
@internal
def _foo(a: int128, b: int128[3], c: int128[3]) -> (int128[3], int128, int128[3]):
    return c, 4, [b[1], a, b[0]]

@external
def foo(a: int128, b: int128[3], c: int128[3]) -> (int128[3], int128, int128[3]):
    return self._foo(a, b, c)
    """,
        (6, [7, 5, 8], [1, 2, 3]),
        [[1, 2, 3], 4, [5, 6, 7]],
    ),
    (
        """
@internal
def _foo(a: int128, b: int128[3], c: int128[3]) -> (int128[3], int128, int128[3]):
    return c, 4, [b[1], a, b[0]]

@external
def foo(a: int128, b: int128[3], c: int128[3]) -> (int128[3], int128, int128[3]):
    return c, 4, self._foo(a, b, c)[2]
    """,
        (6, [7, 5, 8], [1, 2, 3]),
        [[1, 2, 3], 4, [5, 6, 7]],
    ),
]


@pytest.mark.parametrize("source_code,args,expected", tuple_return_sources)
def test_tuple_return_types(get_contract, source_code, args, expected):
    c = get_contract(source_code)

    assert c.foo(*args) == expected
