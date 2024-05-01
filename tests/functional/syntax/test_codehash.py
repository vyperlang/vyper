from vyper.compiler import compile_code
from vyper.utils import keccak256


def test_get_extcodehash(get_contract):
    code = """
a: address

@deploy
def __init__():
    self.a = self

@external
def foo(x: address) -> bytes32:
    return x.codehash

@external
def foo2(x: address) -> bytes32:
    b: address = x
    return b.codehash

@external
def foo3() -> bytes32:
    return self.codehash

@external
def foo4() -> bytes32:
    return self.a.codehash
    """
    compiled = compile_code(code, output_formats=["bytecode_runtime"])
    bytecode = bytes.fromhex(compiled["bytecode_runtime"][2:])
    hash_ = keccak256(bytecode)

    c = get_contract(code)

    assert c.foo(c.address) == hash_
    assert not int(c.foo("0xDeaDbeefdEAdbeefdEadbEEFdeadbeEFdEaDbeeF").hex(), 16)

    assert c.foo2(c.address) == hash_
    assert not int(c.foo2("0xDeaDbeefdEAdbeefdEadbEEFdeadbeEFdEaDbeeF").hex(), 16)

    assert c.foo3() == hash_
    assert c.foo4() == hash_
