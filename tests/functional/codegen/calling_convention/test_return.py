import pytest

from vyper import compile_code
from vyper.exceptions import TypeMismatch

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_correct_abi_right_padding(tester, w3, get_contract_with_gas_estimation):
    selfcall_code_6 = """
@external
def hardtest(arg1: Bytes[64], arg2: Bytes[64]) -> Bytes[128]:
    return concat(arg1, arg2)
    """

    c = get_contract_with_gas_estimation(selfcall_code_6)

    assert c.hardtest(b"hello" * 5, b"hello" * 10) == b"hello" * 15

    # Make sure underlying structe is correctly right padded
    classic_contract = c._classic_contract
    func = classic_contract.functions.hardtest(b"hello" * 5, b"hello" * 10)
    tx = func.build_transaction({"gasPrice": 0})
    del tx["chainId"]
    del tx["gasPrice"]

    tx["from"] = w3.eth.accounts[0]
    res = w3.to_bytes(hexstr=tester.call(tx))

    static_offset = int.from_bytes(res[:32], "big")
    assert static_offset == 32

    dyn_section = res[static_offset:]
    assert len(dyn_section) % 32 == 0  # first right pad assert

    len_value = int.from_bytes(dyn_section[:32], "big")

    assert len_value == len(b"hello" * 15)
    assert dyn_section[32 : 32 + len_value] == b"hello" * 15
    # second right pad assert
    assert dyn_section[32 + len_value :] == b"\x00" * (len(dyn_section) - 32 - len_value)


def test_return_type(get_contract_with_gas_estimation):
    long_string = 35 * "test"

    code = """
struct Chunk:
    a: Bytes[8]
    b: Bytes[8]
    c: int128
chunk: Chunk

@deploy
def __init__():
    self.chunk.a = b"hello"
    self.chunk.b = b"world"
    self.chunk.c = 5678

@external
def out() -> (int128, address):
    return 3333, 0x0000000000000000000000000000000000000001

@external
def out_literals() -> (int128, address, Bytes[6]):
    return 1, 0x0000000000000000000000000000000000000000, b"random"

@external
def out_bytes_first() -> (Bytes[4], int128):
    return b"test", 1234

@external
def out_bytes_a(x: int128, y: Bytes[4]) -> (int128, Bytes[4]):
    return x, y

@external
def out_bytes_b(x: int128, y: Bytes[4]) -> (Bytes[4], int128, Bytes[4]):
    return y, x, y

@external
def four() -> (int128, Bytes[8], Bytes[8], int128):
    return 1234, b"bytes", b"test", 4321

@external
def out_chunk() -> (Bytes[8], int128, Bytes[8]):
    return self.chunk.a, self.chunk.c, self.chunk.b

@external
def out_very_long_bytes() -> (int128, Bytes[1024], int128, address):
    return 5555, b"testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttest", 6666, 0x0000000000000000000000000000000000001234  # noqa
    """

    c = get_contract_with_gas_estimation(code)

    assert c.out() == [3333, "0x0000000000000000000000000000000000000001"]
    assert c.out_literals() == [1, None, b"random"]
    assert c.out_bytes_first() == [b"test", 1234]
    assert c.out_bytes_a(5555555, b"test") == [5555555, b"test"]
    assert c.out_bytes_b(5555555, b"test") == [b"test", 5555555, b"test"]
    assert c.four() == [1234, b"bytes", b"test", 4321]
    assert c.out_chunk() == [b"hello", 5678, b"world"]
    assert c.out_very_long_bytes() == [
        5555,
        long_string.encode(),
        6666,
        "0x0000000000000000000000000000000000001234",
    ]


def test_return_type_signatures(get_contract_with_gas_estimation):
    code = """
@external
def out_literals() -> (int128, address, Bytes[6]):
    return 1, 0x0000000000000000000000000000000000000000, b"random"
    """

    c = get_contract_with_gas_estimation(code)
    assert c._classic_contract.abi[0]["outputs"] == [
        {"type": "int128", "name": ""},
        {"type": "address", "name": ""},
        {"type": "bytes", "name": ""},
    ]


def test_return_tuple_assign(get_contract_with_gas_estimation):
    code = """
@internal
def _out_literals() -> (int128, address, Bytes[10]):
    return 1, 0x0000000000000000000000000000000000000000, b"random"

@external
def out_literals() -> (int128, address, Bytes[10]):
    return self._out_literals()

@external
def test() -> (int128, address, Bytes[10]):
    a: int128 = 0
    b: address = empty(address)
    c: Bytes[10] = b""
    (a, b, c) = self._out_literals()
    return a, b, c
    """

    c = get_contract_with_gas_estimation(code)

    assert c.out_literals() == c.test() == [1, None, b"random"]


def test_return_tuple_assign_storage(get_contract_with_gas_estimation):
    code = """
a: int128
b: address
c: Bytes[20]
d: Bytes[20]

@internal
def _out_literals() -> (int128, Bytes[20], address, Bytes[20]):
    return 1, b"testtesttest", 0x0000000000000000000000000000000000000023, b"random"

@external
def out_literals() -> (int128, Bytes[20], address, Bytes[20]):
    return self._out_literals()

@external
def test1() -> (int128, Bytes[20], address, Bytes[20]):
    self.a, self.c, self.b, self.d = self._out_literals()
    return self.a, self.c, self.b, self.d

@external
def test2() -> (int128, address):
    x: int128 = 0
    x, self.c, self.b, self.d = self._out_literals()
    return x, self.b

@external
def test3() -> (address, int128):
    x: address = empty(address)
    self.a, self.c, x, self.d = self._out_literals()
    return x, self.a
    """

    c = get_contract_with_gas_estimation(code)

    addr = "0x" + "00" * 19 + "23"
    assert c.out_literals() == [1, b"testtesttest", addr, b"random"]
    assert c.out_literals() == c.test1()
    assert c.test2() == [1, c.out_literals()[2]]
    assert c.test3() == [c.out_literals()[2], 1]


@pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_string_inside_tuple(get_contract, string):
    code = f"""
@external
def test_return() -> (String[6], uint256):
    return "{string}", 42
    """
    c1 = get_contract(code)

    code = """
interface jsonabi:
    def test_return() -> (String[6], uint256): view

@external
def test_values(a: address) -> (String[6], uint256):
    return staticcall jsonabi(a).test_return()
    """

    c2 = get_contract(code)
    assert c2.test_values(c1.address) == [string, 42]


@pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_bytes_inside_tuple(get_contract, string):
    code = f"""
@external
def test_return() -> (Bytes[6], uint256):
    return b"{string}", 42
    """
    c1 = get_contract(code)

    code = """
interface jsonabi:
    def test_return() -> (Bytes[6], uint256): view

@external
def test_values(a: address) -> (Bytes[6], uint256):
    return staticcall jsonabi(a).test_return()
    """

    c2 = get_contract(code)
    assert c2.test_values(c1.address) == [bytes(string, "utf-8"), 42]


def test_tuple_return_typecheck(tx_failed, get_contract_with_gas_estimation):
    code = """
@external
def getTimeAndBalance() -> (bool, address):
    return block.timestamp, self.balance
    """
    with pytest.raises(TypeMismatch):
        compile_code(code)


def test_struct_return_abi(get_contract_with_gas_estimation):
    code = """
struct Voter:
    weight: int128
    voted: bool

@external
def test() -> Voter:
    a: Voter = Voter(weight=123, voted=True)
    return a
    """

    out = compile_code(code, output_formats=["abi"])
    abi = out["abi"][0]

    assert abi["name"] == "test"

    c = get_contract_with_gas_estimation(code)

    assert c.test() == (123, True)


def test_single_struct_return_abi(get_contract_with_gas_estimation):
    code = """
struct Voter:
    voted: bool

@external
def test() -> Voter:
    a: Voter = Voter(voted=True)
    return a
    """

    out = compile_code(code, output_formats=["abi"])
    abi = out["abi"][0]

    assert abi["name"] == "test"
    assert abi["outputs"][0]["type"] == "tuple"

    c = get_contract_with_gas_estimation(code)

    assert c.test() == (True,)


def test_struct_return(get_contract_with_gas_estimation):
    code = """
struct Foo:
  x: int128
  y: uint256

_foo: Foo
_foos: HashMap[int128, Foo]

@internal
def priv1() -> Foo:
    return Foo(x= 1, y=2)
@external
def pub1() -> Foo:
    return self.priv1()

@internal
def priv2() -> Foo:
    foo: Foo = Foo(x= 0, y=0)
    foo.x = 3
    foo.y = 4
    return foo
@external
def pub2() -> Foo:
    return self.priv2()

@external
def pub3() -> Foo:
    self._foo = Foo(x= 5, y=6)
    return self._foo

@external
def pub4() -> Foo:
   self._foos[0] = Foo(x= 7, y=8)
   return self._foos[0]

@internal
def return_arg(foo: Foo) -> Foo:
    return foo
@external
def pub5(foo: Foo) -> Foo:
    return self.return_arg(foo)
@external
def pub6() -> Foo:
    foo: Foo = Foo(x= 123, y=456)
    return self.return_arg(foo)
    """
    foo = (123, 456)

    c = get_contract_with_gas_estimation(code)

    assert c.pub1() == (1, 2)
    assert c.pub2() == (3, 4)
    assert c.pub3() == (5, 6)
    assert c.pub4() == (7, 8)
    assert c.pub5(foo) == foo
    assert c.pub6() == foo


def test_single_struct_return(get_contract_with_gas_estimation):
    code = """
struct Foo:
  x: int128

_foo: Foo
_foos: HashMap[int128, Foo]

@internal
def priv1() -> Foo:
    return Foo(x=1)
@external
def pub1() -> Foo:
    return self.priv1()

@internal
def priv2() -> Foo:
    foo: Foo = Foo(x=0)
    foo.x = 3
    return foo
@external
def pub2() -> Foo:
    return self.priv2()

@external
def pub3() -> Foo:
    self._foo = Foo(x=5)
    return self._foo

@external
def pub4() -> Foo:
   self._foos[0] = Foo(x=7)
   return self._foos[0]

@internal
def return_arg(foo: Foo) -> Foo:
    return foo
@external
def pub5(foo: Foo) -> Foo:
    return self.return_arg(foo)
@external
def pub6() -> Foo:
    foo: Foo = Foo(x=123)
    return self.return_arg(foo)
    """
    foo = (123,)

    c = get_contract_with_gas_estimation(code)

    assert c.pub1() == (1,)
    assert c.pub2() == (3,)
    assert c.pub3() == (5,)
    assert c.pub4() == (7,)
    assert c.pub5(foo) == foo
    assert c.pub6() == foo


def test_self_call_in_return_struct(get_contract):
    code = """
struct Foo:
    a: uint256
    b: uint256
    c: uint256
    d: uint256
    e: uint256

@internal
def _foo() -> uint256:
    a: uint256[10] = [6,7,8,9,10,11,12,13,14,15]
    return 3

@external
def foo() -> Foo:
    return Foo(a=1, b=2, c=self._foo(), d=4, e=5)
    """

    c = get_contract(code)

    assert c.foo() == (1, 2, 3, 4, 5)


def test_self_call_in_return_single_struct(get_contract):
    code = """
struct Foo:
    a: uint256

@internal
def _foo() -> uint256:
    a: uint256[10] = [6,7,8,9,10,11,12,13,14,15]
    return 3

@external
def foo() -> Foo:
    return Foo(a=self._foo())
    """

    c = get_contract(code)

    assert c.foo() == (3,)


def test_call_in_call(get_contract):
    code = """
struct Foo:
    a: uint256
    b: uint256
    c: uint256
    d: uint256
    e: uint256

@internal
def _foo(a: uint256, b: uint256, c: uint256) -> Foo:
    return Foo(a=1, b=a, c=b, d=c, e=5)

@internal
def _foo2() -> uint256:
    a: uint256[10] = [6,7,8,9,10,11,12,13,15,16]
    return 4

@external
def foo() -> Foo:
    return self._foo(2, 3, self._foo2())
    """

    c = get_contract(code)

    assert c.foo() == (1, 2, 3, 4, 5)


def test_call_in_call_single_struct(get_contract):
    code = """
struct Foo:
    a: uint256

@internal
def _foo(a: uint256) -> Foo:
    return Foo(a=a)

@internal
def _foo2() -> uint256:
    a: uint256[10] = [6,7,8,9,10,11,12,13,15,16]
    return 4

@external
def foo() -> Foo:
    return self._foo(self._foo2())
    """

    c = get_contract(code)

    assert c.foo() == (4,)


def test_nested_calls_in_struct_return(get_contract):
    code = """
struct Foo:
    a: uint256
    b: uint256
    c: uint256
    d: uint256
    e: uint256
struct Bar:
    a: uint256
    b: uint256

@internal
def _bar(a: uint256, b: uint256, c: uint256) -> Bar:
    return Bar(a=415, b=3)

@internal
def _foo2(a: uint256) -> uint256:
    b: uint256[10] = [6,7,8,9,10,11,12,13,14,15]
    return 99

@internal
def _foo3(a: uint256, b: uint256) -> uint256:
    c: uint256[10] = [14,15,16,17,18,19,20,21,22,23]
    return 42

@internal
def _foo4() -> uint256:
    c: uint256[10] = [14,15,16,17,18,19,20,21,22,23]
    return 4

@external
def foo() -> Foo:
    return Foo(
        a=1,
        b=2,
        c=self._bar(6, 7, self._foo2(self._foo3(9, 11))).b,
        d=self._foo4(),
        e=5
    )
    """

    c = get_contract(code)

    assert c.foo() == (1, 2, 3, 4, 5)


def test_nested_calls_in_single_struct_return(get_contract):
    code = """
struct Foo:
    a: uint256
struct Bar:
    a: uint256
    b: uint256

@internal
def _bar(a: uint256, b: uint256, c: uint256) -> Bar:
    return Bar(a=415, b=3)

@internal
def _foo2(a: uint256) -> uint256:
    b: uint256[10] = [6,7,8,9,10,11,12,13,14,15]
    return 99

@internal
def _foo3(a: uint256, b: uint256) -> uint256:
    c: uint256[10] = [14,15,16,17,18,19,20,21,22,23]
    return 42

@internal
def _foo4() -> uint256:
    c: uint256[10] = [14,15,16,17,18,19,20,21,22,23]
    return 4

@external
def foo() -> Foo:
    return Foo(
        a=self._bar(6, self._foo4(), self._foo2(self._foo3(9, 11))).b,
    )
    """

    c = get_contract(code)

    assert c.foo() == (3,)


def test_external_call_in_return_struct(get_contract):
    code = """
struct Bar:
    a: uint256
    b: uint256
@view
@external
def bar() -> Bar:
    return Bar(a=3, b=4)
    """

    code2 = """
struct Foo:
    a: uint256
    b: uint256
    c: uint256
    d: uint256
    e: uint256
struct Bar:
    a: uint256
    b: uint256
interface IBar:
    def bar() -> Bar: view

@external
def foo(addr: address) -> Foo:
    return Foo(
        a=1,
        b=2,
        c=(staticcall IBar(addr).bar()).a,
        d=4,
        e=5
    )
    """

    c = get_contract(code)
    c2 = get_contract(code2)

    assert c2.foo(c.address) == (1, 2, 3, 4, 5)


def test_external_call_in_return_single_struct(get_contract):
    code = """
struct Bar:
    a: uint256
@view
@external
def bar() -> Bar:
    return Bar(a=3)
    """

    code2 = """
struct Foo:
    a: uint256
struct Bar:
    a: uint256
interface IBar:
    def bar() -> Bar: view

@external
def foo(addr: address) -> Foo:
    return Foo(a=(staticcall IBar(addr).bar()).a)
    """

    c = get_contract(code)
    c2 = get_contract(code2)

    assert c2.foo(c.address) == (3,)


def test_nested_external_call_in_return_struct(get_contract):
    code = """
struct Bar:
    a: uint256
    b: uint256

@view
@external
def bar() -> Bar:
    return Bar(a=3, b=4)

@view
@external
def baz(x: uint256) -> uint256:
    return x+1
    """

    code2 = """
struct Foo:
    a: uint256
    b: uint256
    c: uint256
    d: uint256
    e: uint256
struct Bar:
    a: uint256
    b: uint256

interface IBar:
    def bar() -> Bar: view
    def baz(a: uint256) -> uint256: view

@external
def foo(addr: address) -> Foo:
    return Foo(
        a=1,
        b=2,
        c=(staticcall IBar(addr).bar()).a,
        d=4,
        e=(staticcall IBar(addr).baz((staticcall IBar(addr).bar()).b))
    )
    """

    c = get_contract(code)
    c2 = get_contract(code2)

    assert c2.foo(c.address) == (1, 2, 3, 4, 5)


def test_nested_external_call_in_return_single_struct(get_contract):
    code = """
struct Bar:
    a: uint256

@view
@external
def bar() -> Bar:
    return Bar(a=3)

@view
@external
def baz(x: uint256) -> uint256:
    return x+1
    """

    code2 = """
struct Foo:
    a: uint256
struct Bar:
    a: uint256

interface IBar:
    def bar() -> Bar: view
    def baz(a: uint256) -> uint256: view

@external
def foo(addr: address) -> Foo:
    return Foo(
        a=staticcall IBar(addr).baz((staticcall IBar(addr).bar()).a)
    )
    """

    c = get_contract(code)
    c2 = get_contract(code2)

    assert c2.foo(c.address) == (4,)


@pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_string_inside_struct(get_contract, string):
    code = f"""
struct Person:
    name: String[6]
    age: uint256

@external
def test_return() -> Person:
    return Person(name="{string}", age=42)
    """
    c1 = get_contract(code)

    code = """
struct Person:
    name: String[6]
    age: uint256

interface jsonabi:
    def test_return() -> Person: view

@external
def test_values(a: address) -> Person:
    return staticcall jsonabi(a).test_return()
    """

    c2 = get_contract(code)
    assert c2.test_values(c1.address) == (string, 42)


@pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_string_inside_single_struct(get_contract, string):
    code = f"""
struct Person:
    name: String[6]

@external
def test_return() -> Person:
    return Person(name="{string}")
    """
    c1 = get_contract(code)

    code = """
struct Person:
    name: String[6]

interface jsonabi:
    def test_return() -> Person: view

@external
def test_values(a: address) -> Person:
    return staticcall jsonabi(a).test_return()
    """

    c2 = get_contract(code)
    assert c2.test_values(c1.address) == (string,)
