import pytest

from vyper.compiler import compile_code
from vyper.exceptions import ImmutableViolation


def test_exports_no_uses(make_input_bundle):
    lib1 = """
counter: uint256

@external
def get_counter() -> uint256:
    self.counter += 1
    return self.counter
    """
    main = """
import lib1
exports: lib1.get_counter
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)
        assert e.value._message == "Cannot access `lib1` state!"

        expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
        expected_hint += "top-level statement to your contract"
        assert e.value.hint == expected_hint


def test_exports_no_uses_variable(make_input_bundle):
    lib1 = """
counter: public(uint256)
    """
    main = """
import lib1
exports: lib1.counter
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)
        assert e.value._message == "Cannot access `lib1` state!"

        expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
        expected_hint += "top-level statement to your contract"
        assert e.value.hint == expected_hint


def test_exports_uses_variable(make_input_bundle):
    lib1 = """
counter: public(uint256)
    """
    main = """
import lib1

exports: lib1.counter
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_exports_uses(make_input_bundle):
    lib1 = """
counter: uint256

@external
def get_counter() -> uint256:
    self.counter += 1
    return self.counter
    """
    main = """
import lib1

exports: lib1.get_counter
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_exports_implements(make_input_bundle):
    token_interface = """
@external
def totalSupply() -> uint256:
    ...

@external
def balanceOf(addr: address) -> uint256:
    ...

@external
def transfer(receiver: address, amount: uint256):
    ...
    """
    lib1 = """
import itoken

implements: itoken

@deploy
def __init__(initial_supply: uint256):
    self.totalSupply = initial_supply

totalSupply: public(uint256)
balanceOf: public(HashMap[address, uint256])

@external
def transfer(receiver: address, amount: uint256):
    self.balanceOf[msg.sender] -= amount
    self.balanceOf[receiver] += amount
    """
    main = """
import tokenlib
import itoken

implements: itoken
exports: (tokenlib.totalSupply, tokenlib.balanceOf, tokenlib.transfer)

initializes: tokenlib

@deploy
def __init__():
    tokenlib.__init__(100_000_000)
    """
    input_bundle = make_input_bundle({"tokenlib.vy": lib1, "itoken.vyi": token_interface})
    assert compile_code(main, input_bundle=input_bundle) is not None
