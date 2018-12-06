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


# def test_struct_return(get_contract_with_gas_estimation):
#     code = """
# ### proof-of-concept.vy
# struct Foo:
#   x: int128
#   y: uint256

# _foo: Foo
# _foos: map(int128, Foo)

# @private
# def passFoo(foo: Foo) -> int128:
#     return foo.x

# @private
# def retFoo() -> Foo:
#     return Foo({x: 1})

# @private
# def retFoo2() -> Foo:
#     foo: Foo
#     return foo

# @private
# def retFoo3() -> Foo:
#     return self._foo

# @private
# def retFoo4() -> Foo:
#    return self._foos[0]
#     """

#     c = get_contract_with_gas_estimation(code)

#     assert c.passFoo()
