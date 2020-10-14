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

    assert c.test() == [123, True]


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
    foo = [123, 456]

    c = get_contract_with_gas_estimation(code)

    assert c.pub1() == [1, 2]
    assert c.pub2() == [3, 4]
    assert c.pub3() == [5, 6]
    assert c.pub4() == [7, 8]
    assert c.pub5(foo) == foo
    assert c.pub6() == foo
