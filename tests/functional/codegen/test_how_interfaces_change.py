import json

import pytest
from eth_utils import to_wei

from tests.utils import decimal_to_int
from vyper.compiler import compile_code, compile_from_file_input
from vyper.exceptions import (
    ArgumentException,
    DuplicateImport,
    InterfaceViolation,
    NamespaceCollision,
)

# My goal: to have the same rules for abstract methods and implements
#
# But the rules for abstract methods have to be "correct":
# Any call to the abstract _must_ be a valid call to the override
#
# So we should make it so any call for a method in an interface is a valid call to the method implementing it

def test_recommended_vyi_old(make_input_bundle):
    _interface = """
@view
def name() -> String[1]: ...
    """

    code = """
import _interface
implements: _interface

name: public(String[5])
    """

    input_bundle = make_input_bundle({"_interface.vyi": _interface})

    compile_code(code, input_bundle=input_bundle)

def test_recommended_vyi_new(make_input_bundle):
    _interface = """
@view
def name() -> String[INF]: ...
    """

    code = """
import _interface
implements: _interface

name: public(String[5])
    """

    input_bundle = make_input_bundle({"_interface.vyi": _interface})

    compile_code(code, input_bundle=input_bundle)


def test_IERC20Detailed(make_input_bundle):
    # Works in both since IERC20Detailed was updated
    code = """
from ethereum.ercs import IERC20Detailed

implements: IERC20Detailed

name: public(String[5])

symbol: public(String[2])

decimals: public(uint8)
    """

    compile_code(code)


def test_interface_old(make_input_bundle):
    other = """
@external
@view
def foo(a: Bytes[4]) -> Bytes[4]:
    return a
    """
    
    code = """
import other

implements: other.__interface__

@external
@view
def foo(a: Bytes[5]) -> Bytes[5]: # can return b"12345" which is invalid for other
    return a
    """
    
    input_bundle = make_input_bundle({"other.vy": other})

    compile_code(code, input_bundle=input_bundle)


def test_interface_new(make_input_bundle):
    other = """
@external
@view
def foo(a: Bytes[4]) -> Bytes[4]:
    return a
    """
    
    code = """
import other

implements: other.__interface__

@external
@view
def foo(a: Bytes[5]) -> Bytes[3]: # strictly stronger guarantees
    return slice(a, 0, 3)
    """
    
    input_bundle = make_input_bundle({"other.vy": other})

    compile_code(code, input_bundle=input_bundle)


def test_json_interface_old(make_input_bundle):
    # Note: Any contract implements its own abi
    # But other incompatible contracts as well !
    json_abi = """
        [{
            "stateMutability": "view",
            "type": "function",
            "name": "foo",
            "inputs": [{"name": "a", "type": "bytes"}],
            "outputs": [{"name": "", "type": "bytes"}]
        }]
    """

    code = """
import jsonabi

implements: jsonabi

@external
@view
def foo(a: Bytes[4]) -> Bytes[4]:
    return a
    """

    input_bundle = make_input_bundle({"jsonabi.json": json_abi})

    compile_code(code, input_bundle=input_bundle)


def test_json_interface_new(make_input_bundle):
    # Note: Only Bytes[INF] contracts can implement abis containing bytes
    # But this means only these contracts impement their own abi
    # This might seem surprising, but actually makes sense, as we lose information in the abi
    # So we cannot leverage the same guarantees

    json_abi = """
        [{
            "stateMutability": "view",
            "type": "function",
            "name": "foo",
            "inputs": [{"name": "a", "type": "bytes"}],
            "outputs": [{"name": "", "type": "bytes"}]
        }]
    """

    code = """
import jsonabi

implements: jsonabi

@external
@view
def foo(a: Bytes[INF]) -> Bytes[INF]:
    return a
    """
    pytest.xfail("Bytes[INF] parameters not yet implemented")

    input_bundle = make_input_bundle({"jsonabi.json": json_abi})

    compile_code(code, input_bundle=input_bundle)


# Compilation depends on order:
# test data returned from external interface gets clamped
def test_json_abi_bytes_clampers_3(get_contract, tx_failed, assert_compile_failed, make_input_bundle):
    external_contract = """
@external
def returns_Bytes3() -> Bytes[3]:
    return b"123"
    """

    code = """
import BadJSONInterface

foo: BadJSONInterface

@deploy
def __init__(addr: BadJSONInterface):
    self.foo = addr

@external
def test_fail3() -> Bytes[3]:
    # should revert - returns_Bytes3 is inferred to have return type Bytes[2]
    # (because test_fail3 comes after test_fail1)
    # Shouldn't revert !
    # We call an external method which returns a Bytes[3] and expect a Bytes[3]
    return extcall self.foo.returns_Bytes3()

@external
def test_fail1() -> Bytes[2]:
    # should compile, but raise runtime exception
    return extcall self.foo.returns_Bytes3()

@external
def test_fail2() -> Bytes[2]:
    # should compile, but raise runtime exception
    x: Bytes[2] = extcall self.foo.returns_Bytes3()
    return x
    """

    bad_c = get_contract(external_contract)
    assert bad_c.returns_Bytes3() == b"123"

    bad_json_interface = json.dumps(compile_code(external_contract, output_formats=["abi"])["abi"])
    input_bundle = make_input_bundle({"BadJSONInterface.json": bad_json_interface})

    c = get_contract(code, bad_c.address, input_bundle=input_bundle)

    with tx_failed():
        c.test_fail3()
    with tx_failed():
        c.test_fail1()
    with tx_failed():
        c.test_fail2()
