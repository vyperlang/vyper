import pytest

from vyper.compiler import compile_code

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_struct_return_abi(get_contract_with_gas_estimation):
    code = """
struct Voter:
    weight: int128
    voted: bool

@external
def test() -> Voter:
    a: Voter = Voter({weight: 123, voted: True})
    return a
    """

    out = compile_code(code, ["abi"])
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
    a: Voter = Voter({voted: True})
    return a
    """

    out = compile_code(code, ["abi"])
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
    return Foo({x: 1, y: 2})
@external
def pub1() -> Foo:
    return self.priv1()

@internal
def priv2() -> Foo:
    foo: Foo = Foo({x: 0, y: 0})
    foo.x = 3
    foo.y = 4
    return foo
@external
def pub2() -> Foo:
    return self.priv2()

@external
def pub3() -> Foo:
    self._foo = Foo({x: 5, y: 6})
    return self._foo

@external
def pub4() -> Foo:
   self._foos[0] = Foo({x: 7, y: 8})
   return self._foos[0]

@internal
def return_arg(foo: Foo) -> Foo:
    return foo
@external
def pub5(foo: Foo) -> Foo:
    return self.return_arg(foo)
@external
def pub6() -> Foo:
    foo: Foo = Foo({x: 123, y: 456})
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
    return Foo({x: 1})
@external
def pub1() -> Foo:
    return self.priv1()

@internal
def priv2() -> Foo:
    foo: Foo = Foo({x: 0})
    foo.x = 3
    return foo
@external
def pub2() -> Foo:
    return self.priv2()

@external
def pub3() -> Foo:
    self._foo = Foo({x: 5})
    return self._foo

@external
def pub4() -> Foo:
   self._foos[0] = Foo({x: 7})
   return self._foos[0]

@internal
def return_arg(foo: Foo) -> Foo:
    return foo
@external
def pub5(foo: Foo) -> Foo:
    return self.return_arg(foo)
@external
def pub6() -> Foo:
    foo: Foo = Foo({x: 123})
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
    return Foo({a:1, b:2, c:self._foo(), d:4, e:5})
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
    return Foo({a:self._foo()})
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
    return Foo({a:1, b:a, c:b, d:c, e:5})

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
    return Foo({a:a})

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
    return Bar({a:415, b:3})

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
    return Foo({
        a:1,
        b:2,
        c:self._bar(6, 7, self._foo2(self._foo3(9, 11))).b,
        d:self._foo4(),
        e:5
    })
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
    return Bar({a:415, b:3})

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
    return Foo({
        a:self._bar(6, self._foo4(), self._foo2(self._foo3(9, 11))).b,
    })
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
    return Bar({a:3, b:4})
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
    return Foo({
        a:1,
        b:2,
        c:IBar(addr).bar().a,
        d:4,
        e:5
    })
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
    return Bar({a:3})
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
    return Foo({
        a:IBar(addr).bar().a
    })
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
    return Bar({a:3, b:4})

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
    return Foo({
        a:1,
        b:2,
        c:IBar(addr).bar().a,
        d:4,
        e:IBar(addr).baz(IBar(addr).bar().b)
    })
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
    return Bar({a:3})

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
    return Foo({
        a:IBar(addr).baz(IBar(addr).bar().a)
    })
    """

    c = get_contract(code)
    c2 = get_contract(code2)

    assert c2.foo(c.address) == (4,)
