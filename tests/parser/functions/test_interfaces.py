from decimal import Decimal
import json

import pytest

from vyper.compiler import compile_code
from vyper.exceptions import (
    ArgumentException,
    InterfaceViolation,
    StructureException,
    NamespaceCollision,
)


def test_basic_extract_interface():
    code = """
# Events

event Transfer:
    _from: address
    _to: address
    _value: uint256

# Functions

@view
@external
def allowance(_owner: address, _spender: address) -> (uint256, uint256):
    return 1, 2
    """

    out = compile_code(code, output_formats=["interface"])
    out = out["interface"]
    code_pass = "\n".join(code.split("\n")[:-2] + ["    pass"])  # replace with a pass statement.

    assert code_pass.strip() == out.strip()


def test_basic_extract_external_interface():
    code = """
@view
@external
def allowance(_owner: address, _spender: address) -> (uint256, uint256):
    return 1, 2

@external
def test(_owner: address):
    pass

@view
@internal
def _prive(_owner: address, _spender: address) -> (uint256, uint256):
    return 1, 2
    """

    interface = """
# External Interfaces
interface One:
    def allowance(_owner: address, _spender: address) -> (uint256, uint256): view
    def test(_owner: address): nonpayable
    """

    out = compile_code(code, contract_name="One.vy", output_formats=["external_interface"])[
        "external_interface"
    ]

    assert interface.strip() == out.strip()


def test_basic_interface_implements(assert_compile_failed):
    code = """
from vyper.interfaces import ERC20

implements: ERC20

@external
def test() -> bool:
    return True
    """

    assert_compile_failed(lambda: compile_code(code), InterfaceViolation)


def test_external_interface_parsing(make_input_bundle, assert_compile_failed):
    interface_code = """
@external
def foo() -> uint256:
    pass

@external
def bar() -> uint256:
    pass
    """

    input_bundle = make_input_bundle({"a.vy": interface_code})

    code = """
import a as FooBarInterface

implements: FooBarInterface

@external
def foo() -> uint256:
    return 1

@external
def bar() -> uint256:
    return 2
    """

    assert compile_code(code, input_bundle=input_bundle)

    not_implemented_code = """
import a as FooBarInterface

implements: FooBarInterface

@external
def foo() -> uint256:
    return 1

    """

    assert_compile_failed(
        lambda: compile_code(not_implemented_code, input_bundle=input_bundle), InterfaceViolation
    )


def test_missing_event(make_input_bundle, assert_compile_failed):
    interface_code = """
event Foo:
    a: uint256
    """

    input_bundle = make_input_bundle({"a.vy": interface_code})

    not_implemented_code = """
import a as FooBarInterface

implements: FooBarInterface

@external
def bar() -> uint256:
    return 1
    """

    assert_compile_failed(
        lambda: compile_code(not_implemented_code, input_bundle=input_bundle), InterfaceViolation
    )


# check that event types match
def test_malformed_event(make_input_bundle, assert_compile_failed):
    interface_code = """
event Foo:
    a: uint256
    """

    input_bundle = make_input_bundle({"a.vy": interface_code})

    not_implemented_code = """
import a as FooBarInterface

implements: FooBarInterface

event Foo:
    a: int128

@external
def bar() -> uint256:
    return 1
    """

    assert_compile_failed(
        lambda: compile_code(not_implemented_code, input_bundle=input_bundle), InterfaceViolation
    )


# check that event non-indexed arg needs to match interface
def test_malformed_events_indexed(make_input_bundle, assert_compile_failed):
    interface_code = """
event Foo:
    a: uint256
    """

    input_bundle = make_input_bundle({"a.vy": interface_code})

    not_implemented_code = """
import a as FooBarInterface

implements: FooBarInterface

# a should not be indexed
event Foo:
    a: indexed(uint256)

@external
def bar() -> uint256:
    return 1
    """

    assert_compile_failed(
        lambda: compile_code(not_implemented_code, input_bundle=input_bundle), InterfaceViolation
    )


# check that event indexed arg needs to match interface
def test_malformed_events_indexed2(make_input_bundle, assert_compile_failed):
    interface_code = """
event Foo:
    a: indexed(uint256)
    """

    input_bundle = make_input_bundle({"a.vy": interface_code})

    not_implemented_code = """
import a as FooBarInterface

implements: FooBarInterface

# a should be indexed
event Foo:
    a: uint256

@external
def bar() -> uint256:
    return 1
    """

    assert_compile_failed(
        lambda: compile_code(not_implemented_code, input_bundle=input_bundle), InterfaceViolation
    )


VALID_IMPORT_CODE = [
    # import statement, import path without suffix
    ("import a as Foo", "a.vy"),
    ("import b.a as Foo", "b/a.vy"),
    ("import Foo as Foo", "Foo.vy"),
    ("from a import Foo", "a/Foo.vy"),
    ("from b.a import Foo", "b/a/Foo.vy"),
    ("from .a import Foo", "./a/Foo.vy"),
    ("from ..a import Foo", "../a/Foo.vy"),
]


@pytest.mark.parametrize("code,filename", VALID_IMPORT_CODE)
def test_extract_file_interface_imports(code, filename, make_input_bundle):
    input_bundle = make_input_bundle({filename: ""})

    assert compile_code(code, input_bundle=input_bundle) is not None


BAD_IMPORT_CODE = [
    ("import a", StructureException),  # must alias absolute imports
    ("import a as A\nimport a as A", NamespaceCollision),
    ("from b import a\nfrom . import a", NamespaceCollision),
    ("from . import a\nimport a as a", NamespaceCollision),
    ("import a as a\nfrom . import a", NamespaceCollision),
]


@pytest.mark.parametrize("code,exception_type", BAD_IMPORT_CODE)
def test_extract_file_interface_imports_raises(
    code, exception_type, assert_compile_failed, make_input_bundle
):
    input_bundle = make_input_bundle({"a.vy": "", "b/a.vy": ""})  # dummy
    assert_compile_failed(lambda: compile_code(code, input_bundle=input_bundle), exception_type)


def test_external_call_to_interface(w3, get_contract, make_input_bundle):
    token_code = """
balanceOf: public(HashMap[address, uint256])

@external
def transfer(to: address, _value: uint256):
    self.balanceOf[to] += _value
    """

    input_bundle = make_input_bundle({"one.vy": token_code})

    code = """
import one as TokenCode

interface EPI:
    def test() -> uint256: view


token_address: TokenCode


@external
def __init__(_token_address: address):
    self.token_address = TokenCode(_token_address)


@external
def test():
    self.token_address.transfer(msg.sender, 1000)
    """

    erc20 = get_contract(token_code)
    test_c = get_contract(code, *[erc20.address], input_bundle=input_bundle)

    sender = w3.eth.accounts[0]
    assert erc20.balanceOf(sender) == 0

    test_c.test(transact={})
    assert erc20.balanceOf(sender) == 1000


@pytest.mark.parametrize(
    "kwarg,typ,expected",
    [
        ("max_value(uint256)", "uint256", 2**256 - 1),
        ("min_value(int128)", "int128", -(2**127)),
        ("empty(uint8[2])", "uint8[2]", [0, 0]),
        ('method_id("vyper()", output_type=bytes4)', "bytes4", b"\x82\xcbE\xfb"),
        ("epsilon(decimal)", "decimal", Decimal("1E-10")),
    ],
)
def test_external_call_to_interface_kwarg(get_contract, kwarg, typ, expected, make_input_bundle):
    code_a = f"""
@external
@view
def foo(_max: {typ} = {kwarg}) -> {typ}:
    return _max
    """

    input_bundle = make_input_bundle({"one.vy": code_a})

    code_b = f"""
import one as ContractA

@external
@view
def bar(a_address: address) -> {typ}:
    return ContractA(a_address).foo()
    """

    contract_a = get_contract(code_a)
    contract_b = get_contract(code_b, *[contract_a.address], input_bundle=input_bundle)

    assert contract_b.bar(contract_a.address) == expected


def test_external_call_to_builtin_interface(w3, get_contract):
    token_code = """
balanceOf: public(HashMap[address, uint256])

@external
def transfer(to: address, _value: uint256) -> bool:
    self.balanceOf[to] += _value
    return True
    """

    code = """
from vyper.interfaces import ERC20


token_address: ERC20


@external
def __init__(_token_address: address):
    self.token_address = ERC20(_token_address)


@external
def test():
    self.token_address.transfer(msg.sender, 1000)
    """

    erc20 = get_contract(token_code)
    test_c = get_contract(code, *[erc20.address])

    sender = w3.eth.accounts[0]
    assert erc20.balanceOf(sender) == 0

    test_c.test(transact={})
    assert erc20.balanceOf(sender) == 1000


def test_address_member(w3, get_contract):
    code = """
interface Foo:
    def foo(): payable

f: Foo

@external
def test(addr: address):
    self.f = Foo(addr)
    assert self.f.address == addr
    """
    c = get_contract(code)
    for address in w3.eth.accounts:
        c.test(address)


# test data returned from external interface gets clamped
@pytest.mark.parametrize("typ", ("int128", "uint8"))
def test_external_interface_int_clampers(get_contract, assert_tx_failed, typ):
    external_contract = f"""
@external
def ok() -> {typ}:
    return 1

@external
def should_fail() -> int256:
    return -2**255 # OOB for all int/uint types with less than 256 bits
    """

    code = f"""
interface BadContract:
    def ok() -> {typ}: view
    def should_fail() -> {typ}: view

foo: BadContract

@external
def __init__(addr: BadContract):
    self.foo = addr


@external
def test_ok() -> {typ}:
    return self.foo.ok()

@external
def test_fail() -> {typ}:
    return self.foo.should_fail()

@external
def test_fail2() -> {typ}:
    x: {typ} = self.foo.should_fail()
    return x

@external
def test_fail3() -> int256:
    return convert(self.foo.should_fail(), int256)
    """

    bad_c = get_contract(external_contract)
    c = get_contract(code, bad_c.address)
    assert bad_c.ok() == 1
    assert bad_c.should_fail() == -(2**255)

    assert c.test_ok() == 1
    assert_tx_failed(lambda: c.test_fail())
    assert_tx_failed(lambda: c.test_fail2())
    assert_tx_failed(lambda: c.test_fail3())


# test data returned from external interface gets clamped
def test_external_interface_bytes_clampers(get_contract, assert_tx_failed):
    external_contract = """
@external
def ok() -> Bytes[2]:
    return b"12"

@external
def should_fail() -> Bytes[3]:
    return b"123"
    """

    code = """
interface BadContract:
    def ok() -> Bytes[2]: view
    def should_fail() -> Bytes[2]: view

foo: BadContract

@external
def __init__(addr: BadContract):
    self.foo = addr


@external
def test_ok() -> Bytes[2]:
    return self.foo.ok()

@external
def test_fail1() -> Bytes[3]:
    return self.foo.should_fail()

@external
def test_fail2() -> Bytes[3]:
    return concat(self.foo.should_fail(), b"")
    """

    bad_c = get_contract(external_contract)
    c = get_contract(code, bad_c.address)
    assert bad_c.ok() == b"12"
    assert bad_c.should_fail() == b"123"

    assert c.test_ok() == b"12"
    assert_tx_failed(lambda: c.test_fail1())
    assert_tx_failed(lambda: c.test_fail2())


# test data returned from external interface gets clamped
def test_json_abi_bytes_clampers(
    get_contract, assert_tx_failed, assert_compile_failed, make_input_bundle
):
    external_contract = """
@external
def returns_Bytes3() -> Bytes[3]:
    return b"123"
    """

    should_not_compile = """
import BadJSONInterface as BadJSONInterface
@external
def foo(x: BadJSONInterface) -> Bytes[2]:
    return slice(x.returns_Bytes3(), 0, 2)
    """

    code = """
import BadJSONInterface as BadJSONInterface

foo: BadJSONInterface

@external
def __init__(addr: BadJSONInterface):
    self.foo = addr


@external
def test_fail1() -> Bytes[2]:
    # should compile, but raise runtime exception
    return self.foo.returns_Bytes3()

@external
def test_fail2() -> Bytes[2]:
    # should compile, but raise runtime exception
    x: Bytes[2] = self.foo.returns_Bytes3()
    return x

@external
def test_fail3() -> Bytes[3]:
    # should revert - returns_Bytes3 is inferred to have return type Bytes[2]
    # (because test_fail3 comes after test_fail1)
    return self.foo.returns_Bytes3()

    """

    bad_c = get_contract(external_contract)

    bad_json_interface = json.dumps(compile_code(external_contract, output_formats=["abi"])["abi"])
    input_bundle = make_input_bundle({"BadJSONInterface.json": bad_json_interface})

    assert_compile_failed(
        lambda: get_contract(should_not_compile, input_bundle=input_bundle), ArgumentException
    )

    c = get_contract(code, bad_c.address, input_bundle=input_bundle)
    assert bad_c.returns_Bytes3() == b"123"

    assert_tx_failed(lambda: c.test_fail1())
    assert_tx_failed(lambda: c.test_fail2())
    assert_tx_failed(lambda: c.test_fail3())


def test_units_interface(w3, get_contract, make_input_bundle):
    code = """
import balanceof as BalanceOf

implements: BalanceOf

@external
@view
def balanceOf(owner: address) -> uint256:
    return as_wei_value(1, "ether")
    """

    interface_code = """
@external
@view
def balanceOf(owner: address) -> uint256:
    pass
    """

    input_bundle = make_input_bundle({"balanceof.vy": interface_code})

    c = get_contract(code, input_bundle=input_bundle)

    assert c.balanceOf(w3.eth.accounts[0]) == w3.to_wei(1, "ether")


def test_simple_implements(make_input_bundle):
    interface_code = """
@external
def foo() -> uint256:
    pass
    """

    code = """
import a as FooInterface

implements: FooInterface

@external
def foo() -> uint256:
    return 1
    """

    input_bundle = make_input_bundle({"a.vy": interface_code})

    assert compile_code(code, input_bundle=input_bundle) is not None


def test_self_interface_is_allowed(get_contract):
    code = """
interface Bar:
    def foo() -> uint256: view

@external
def foo() -> uint256 :
    return 42

@external
def bar() -> uint256:
    return Bar(self).foo()
"""
    c = get_contract(code)
    assert c.bar() == 42


def test_self_interface_via_storage(get_contract):
    code = """
interface Bar:
    def foo() -> uint256: view

bar_contract: Bar

@external
def __init__():
    self.bar_contract = Bar(self)

@external
def foo() -> uint256 :
    return 42

@external
def bar() -> uint256:
    return self.bar_contract.foo()
    """
    c = get_contract(code)
    assert c.bar() == 42


def test_self_interface_via_calldata(get_contract):
    code = """
interface Bar:
    def foo() -> uint256: view

@external
def foo() -> uint256 :
    return 42

@external
def bar(a: address) -> uint256:
    return Bar(a).foo()
    """
    c = get_contract(code)
    assert c.bar(c.address) == 42


type_str_params = [
    ("int128", -33),
    ("uint256", 42),
    ("bool", True),
    ("address", "0x1234567890123456789012345678901234567890"),
    ("bytes32", b"bytes32bytes32bytes32bytes32poop"),
    ("decimal", Decimal("3.1337")),
    ("Bytes[4]", b"newp"),
    ("String[6]", "potato"),
]

interface_test_code = """
@external
@view
def test_json(a: {0}) -> {0}:
    return a
    """


def convert_v1_abi(abi):
    new_abi = []
    for func_abi in abi:
        if "stateMutability" in func_abi:
            mutability = func_abi["stateMutability"]
            del func_abi["stateMutability"]
            if mutability == "payable":
                func_abi["constant"] = False
                func_abi["payable"] = True
            elif mutability == "view":
                func_abi["constant"] = True
                func_abi["payable"] = False
            elif mutability == "pure":
                # NOTE: pure "changes" to "view"
                func_abi["constant"] = True
                func_abi["payable"] = False
            else:  # "nonpayable"
                func_abi["constant"] = False
                func_abi["payable"] = False
        else:  # Assume "nonpayable" by default
            func_abi["constant"] = False
            func_abi["payable"] = False
        new_abi.append(func_abi)
    return new_abi


@pytest.mark.parametrize("type_str", [i[0] for i in type_str_params])
def test_json_interface_implements(type_str, make_input_bundle, make_file):
    code = interface_test_code.format(type_str)

    abi = compile_code(code, output_formats=["abi"])["abi"]

    code = f"import jsonabi as jsonabi\nimplements: jsonabi\n{code}"

    input_bundle = make_input_bundle({"jsonabi.json": json.dumps(abi)})

    compile_code(code, input_bundle=input_bundle)

    # overwrite the file
    make_file("jsonabi.json", json.dumps(convert_v1_abi(abi)))

    compile_code(code, input_bundle=input_bundle)


@pytest.mark.parametrize("type_str,value", type_str_params)
def test_json_interface_calls(get_contract, type_str, value, make_input_bundle, make_file):
    code = interface_test_code.format(type_str)

    abi = compile_code(code, output_formats=["abi"])["abi"]
    c1 = get_contract(code)

    code = f"""
import jsonabi as jsonabi

@external
@view
def test_call(a: address, b: {type_str}) -> {type_str}:
    return jsonabi(a).test_json(b)
    """
    input_bundle = make_input_bundle({"jsonabi.json": json.dumps(abi)})

    c2 = get_contract(code, input_bundle=input_bundle)
    assert c2.test_call(c1.address, value) == value

    make_file("jsonabi.json", json.dumps(convert_v1_abi(abi)))
    c3 = get_contract(code, input_bundle=input_bundle)
    assert c3.test_call(c1.address, value) == value
