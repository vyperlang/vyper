from decimal import Decimal

import pytest

from vyper.ast.signatures.interface import extract_sigs
from vyper.builtin_interfaces import ERC20, ERC721
from vyper.cli.utils import extract_file_interface_imports
from vyper.compiler import compile_code, compile_codes
from vyper.exceptions import InterfaceViolation, StructureException


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

    out = compile_code(code, ["interface"])
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

    out = compile_codes({"one.vy": code}, ["external_interface"])["one.vy"]
    out = out["external_interface"]

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


def test_builtin_interfaces_parse():
    assert len(extract_sigs({"type": "vyper", "code": ERC20.interface_code})) == 6
    assert len(extract_sigs({"type": "vyper", "code": ERC721.interface_code})) == 10


def test_extract_sigs_ignores_imports():
    interface_code = """
{}

@external
def foo() -> uint256:
    pass
    """

    base = extract_sigs({"type": "vyper", "code": interface_code.format("")})

    for stmt in ("import x as x", "from x import y"):
        sigs = extract_sigs({"type": "vyper", "code": interface_code.format(stmt)})
        assert [type(i) for i in base] == [type(i) for i in sigs]


def test_external_interface_parsing(assert_compile_failed):
    interface_code = """
@external
def foo() -> uint256:
    pass

@external
def bar() -> uint256:
    pass
    """

    interface_codes = {"FooBarInterface": {"type": "vyper", "code": interface_code}}

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

    assert compile_code(code, interface_codes=interface_codes)

    not_implemented_code = """
import a as FooBarInterface

implements: FooBarInterface

@external
def foo() -> uint256:
    return 1

    """

    assert_compile_failed(
        lambda: compile_code(not_implemented_code, interface_codes=interface_codes),
        InterfaceViolation,
    )


def test_missing_event(assert_compile_failed):
    interface_code = """
event Foo:
    a: uint256
    """

    interface_codes = {"FooBarInterface": {"type": "vyper", "code": interface_code}}

    not_implemented_code = """
import a as FooBarInterface

implements: FooBarInterface

@external
def bar() -> uint256:
    return 1
    """

    assert_compile_failed(
        lambda: compile_code(not_implemented_code, interface_codes=interface_codes),
        InterfaceViolation,
    )


def test_malformed_event(assert_compile_failed):
    interface_code = """
event Foo:
    a: uint256
    """

    interface_codes = {"FooBarInterface": {"type": "vyper", "code": interface_code}}

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
        lambda: compile_code(not_implemented_code, interface_codes=interface_codes),
        InterfaceViolation,
    )


VALID_IMPORT_CODE = [
    # import statement, import path without suffix
    ("import a as Foo", "a"),
    ("import b.a as Foo", "b/a"),
    ("import Foo as Foo", "Foo"),
    ("from a import Foo", "a/Foo"),
    ("from b.a import Foo", "b/a/Foo"),
    ("from .a import Foo", "./a/Foo"),
    ("from ..a import Foo", "../a/Foo"),
]


@pytest.mark.parametrize("code", VALID_IMPORT_CODE)
def test_extract_file_interface_imports(code):

    assert extract_file_interface_imports(code[0]) == {"Foo": code[1]}


BAD_IMPORT_CODE = [
    "import a",  # must alias absolute imports
    "import a as A\nimport a as A",  # namespace collisions
    "from b import a\nfrom a import a",
    "from . import a\nimport a as a",
    "import a as a\nfrom . import a",
]


@pytest.mark.parametrize("code", BAD_IMPORT_CODE)
def test_extract_file_interface_imports_raises(code, assert_compile_failed):
    assert_compile_failed(lambda: extract_file_interface_imports(code), StructureException)


def test_external_call_to_interface(w3, get_contract):
    token_code = """
balanceOf: public(HashMap[address, uint256])

@external
def transfer(to: address, _value: uint256):
    self.balanceOf[to] += _value
    """

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
    test_c = get_contract(
        code, *[erc20.address], interface_codes={"TokenCode": {"type": "vyper", "code": token_code}}
    )

    sender = w3.eth.accounts[0]
    assert erc20.balanceOf(sender) == 0

    test_c.test(transact={})
    assert erc20.balanceOf(sender) == 1000


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
    test_c = get_contract(
        code, *[erc20.address], interface_codes={"TokenCode": {"type": "vyper", "code": token_code}}
    )

    sender = w3.eth.accounts[0]
    assert erc20.balanceOf(sender) == 0

    test_c.test(transact={})
    assert erc20.balanceOf(sender) == 1000


def test_units_interface(w3, get_contract):
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
    interface_codes = {"BalanceOf": {"type": "vyper", "code": interface_code}}
    c = get_contract(code, interface_codes=interface_codes)

    assert c.balanceOf(w3.eth.accounts[0]) == w3.toWei(1, "ether")


def test_local_and_global_interface_namespaces():
    interface_code = """
@external
def foo() -> uint256:
    pass
    """

    global_interface_codes = {
        "FooInterface": {"type": "vyper", "code": interface_code},
        "BarInterface": {"type": "vyper", "code": interface_code},
    }
    local_interface_codes = {
        "FooContract": {"FooInterface": {"type": "vyper", "code": interface_code}},
        "BarContract": {"BarInterface": {"type": "vyper", "code": interface_code}},
    }

    code = """
import a as {0}

implements: {0}

@external
def foo() -> uint256:
    return 1
    """

    codes = {"FooContract": code.format("FooInterface"), "BarContract": code.format("BarInterface")}

    global_compiled = compile_codes(codes, interface_codes=global_interface_codes)
    local_compiled = compile_codes(codes, interface_codes=local_interface_codes)
    assert global_compiled == local_compiled


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
def test_json_interface_implements(type_str):
    code = interface_test_code.format(type_str)

    abi = compile_code(code, ["abi"])["abi"]
    code = f"import jsonabi as jsonabi\nimplements: jsonabi\n{code}"
    compile_code(code, interface_codes={"jsonabi": {"type": "json", "code": abi}})
    compile_code(code, interface_codes={"jsonabi": {"type": "json", "code": convert_v1_abi(abi)}})


@pytest.mark.parametrize("type_str,value", type_str_params)
def test_json_interface_calls(get_contract, type_str, value):
    code = interface_test_code.format(type_str)

    abi = compile_code(code, ["abi"])["abi"]
    c1 = get_contract(code)

    code = f"""
import jsonabi as jsonabi

@external
@view
def test_call(a: address, b: {type_str}) -> {type_str}:
    return jsonabi(a).test_json(b)
    """
    c2 = get_contract(code, interface_codes={"jsonabi": {"type": "json", "code": abi}})
    assert c2.test_call(c1.address, value) == value
    c3 = get_contract(
        code, interface_codes={"jsonabi": {"type": "json", "code": convert_v1_abi(abi)}}
    )
    assert c3.test_call(c1.address, value) == value
