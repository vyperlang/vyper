from vyper.compiler import compile_code


def test_struct_return_abi(get_contract_with_gas_estimation):
    code = """
struct Voter:
    weight: int128
    voted: bool

@public
def test() -> Voter:
    a: Voter = Voter({weight: 123, voted: True})
    return a
    """

    out = compile_code(code, ['abi'])
    abi = out['abi'][0]

    assert abi['name'] == 'test'

    c = get_contract_with_gas_estimation(code)

    assert c.test() == [123, True]


def test_struct_return(get_contract_with_gas_estimation):
    code = """
struct Foo:
  x: int128
  y: uint256

_foo: Foo
_foos: map(int128, Foo)

@private
def priv1() -> Foo:
    return Foo({x: 1, y: 2})
@public
def pub1() -> Foo:
    return self.priv1()

@private
def priv2() -> Foo:
    foo: Foo
    return foo
@public
def pub2() -> Foo:
    return self.priv2()

@public
def pub3() -> Foo:
    return self._foo

@public
def pub4() -> Foo:
   return self._foos[0]

#@private
#def priv5(foo: Foo) -> Foo:
#    return foo
#@public
#def pub5(foo: Foo) -> Foo:
#    return self.priv5(foo)
    """
    foo = [123, 456]

    c = get_contract_with_gas_estimation(code)

    assert c.pub1() == [1,2]
    #assert c.pub5(foo) == foo
