import pytest

from vyper.compiler import (
    compile_code,
    compile_codes,
)
from vyper.exceptions import (
    StructureException,
)
from vyper.interfaces import (
    ERC20,
    ERC721,
)
from vyper.signatures.interface import (
    extract_file_interface_imports,
    extract_sigs,
)


def test_basic_extract_interface():
    code = """
# Events

Transfer: event({_from: address, _to: address, _value: uint256})

# Functions

@constant
@public
def allowance(_owner: address, _spender: address) -> (uint256, uint256):
    return 1, 2
    """

    out = compile_code(code, ['interface'])
    out = out['interface']
    code_pass = '\n'.join(code.split('\n')[:-2] + ['    pass'])  # replace with a pass statement.

    assert code_pass.strip() == out.strip()


def test_basic_extract_external_interface():
    code = """
@constant
@public
def allowance(_owner: address, _spender: address) -> (uint256, uint256):
    return 1, 2

@public
def test(_owner: address):
    pass

@constant
@private
def _prive(_owner: address, _spender: address) -> (uint256, uint256):
    return 1, 2
    """

    interface = """
# External Contracts
contract One:
    def allowance(_owner: address, _spender: address) -> (uint256, uint256): constant
    def test(_owner: address): modifying
    """

    out = compile_codes({'one.vy': code}, ['external_interface'])['one.vy']
    out = out['external_interface']

    assert interface.strip() == out.strip()


def test_basic_interface_implements(assert_compile_failed):
    code = """
from vyper.interfaces import ERC20

implements: ERC20


@public
def test() -> bool:
    return True
    """

    assert_compile_failed(
        lambda: compile_code(code),
        StructureException
    )


def test_builtin_interfaces_parse():
    assert len(extract_sigs({'type': 'vyper', 'code': ERC20.interface_code})) == 8
    assert len(extract_sigs({'type': 'vyper', 'code': ERC721.interface_code})) == 13


def test_extract_sigs_ignores_imports():
    interface_code = """
{}

@public
def foo() -> uint256:
    pass
    """

    base = extract_sigs({'type': 'vyper', 'code': interface_code.format("")})

    for stmt in ("import x as x", "from x import y"):
        sigs = extract_sigs({'type': 'vyper', 'code': interface_code.format(stmt)})
        assert [type(i) for i in base] == [type(i) for i in sigs]


def test_external_interface_parsing(assert_compile_failed):
    interface_code = """
@public
def foo() -> uint256:
    pass

@public
def bar() -> uint256:
    pass
    """

    interface_codes = {
        'FooBarInterface': {
            'type': 'vyper',
            'code': interface_code
        }
    }

    code = """
import a as FooBarInterface

implements: FooBarInterface

@public
def foo() -> uint256:
    return 1

@public
def bar() -> uint256:
    return 2
    """

    assert compile_code(code, interface_codes=interface_codes)

    not_implemented_code = """
import a as FooBarInterface

implements: FooBarInterface

@public
def foo() -> uint256:
    return 1

    """

    assert_compile_failed(
        lambda: compile_code(not_implemented_code, interface_codes=interface_codes),
        StructureException
    )


VALID_IMPORT_CODE = [
    # import statement, import path without suffix
    ("import a as Foo", 'a'),
    ("import b.a as Foo", 'b/a'),
    ("import Foo as Foo", 'Foo'),
    ("from a import Foo", 'a/Foo'),
    ("from b.a import Foo", 'b/a/Foo'),
    ("from .a import Foo", './a/Foo'),
    ("from ..a import Foo", '../a/Foo'),
]


@pytest.mark.parametrize('code', VALID_IMPORT_CODE)
def test_extract_file_interface_imports(code):

    assert extract_file_interface_imports(code[0]) == {'Foo': code[1]}


BAD_IMPORT_CODE = [
    "import a",  # must alias absolute imports
    "from a import a as A",  # cannot alias from imports
    "from ..a import a as A",
    "import a as A\nimport a as A",  # namespace collisions
    "from b import a\nfrom a import a",
    "from . import a\nimport a as a",
    "import a as a\nfrom . import a",
]


@pytest.mark.parametrize('code', BAD_IMPORT_CODE)
def test_extract_file_interface_imports_raises(code, assert_compile_failed):
    assert_compile_failed(
        lambda: extract_file_interface_imports(code),
        StructureException
    )


def test_external_call_to_interface(w3, get_contract):
    token_code = """
balanceOf: public(map(address, uint256))

@public
def transfer(to: address, value: uint256):
    self.balanceOf[to] += value
    """

    code = """
import one as TokenCode

contract EPI:
    def test() -> uint256: constant


token_address: TokenCode


@public
def __init__(_token_address: address):
    self.token_address = TokenCode(_token_address)


@public
def test():
    self.token_address.transfer(msg.sender, 1000)
    """

    erc20 = get_contract(token_code)
    test_c = get_contract(code, *[erc20.address], interface_codes={
        'TokenCode': {'type': 'vyper', 'code': token_code}
    })

    sender = w3.eth.accounts[0]
    assert erc20.balanceOf(sender) == 0

    test_c.test(transact={})
    assert erc20.balanceOf(sender) == 1000


def test_external_call_to_builtin_interface(w3, get_contract):
    token_code = """
balanceOf: public(map(address, uint256))

@public
def transfer(to: address, value: uint256):
    self.balanceOf[to] += value
    """

    code = """
from vyper.interfaces import ERC20


token_address: ERC20


@public
def __init__(_token_address: address):
    self.token_address = ERC20(_token_address)


@public
def test():
    self.token_address.transfer(msg.sender, 1000)
    """

    erc20 = get_contract(token_code)
    test_c = get_contract(code, *[erc20.address], interface_codes={
        'TokenCode': {
            'type': 'vyper',
            'code': token_code
        }
    })

    sender = w3.eth.accounts[0]
    assert erc20.balanceOf(sender) == 0

    test_c.test(transact={})
    assert erc20.balanceOf(sender) == 1000


def test_json_interface(get_contract):
    code = """
import folding as Folding

implements: Folding

@public
def test(a: uint256) -> uint256:
    return 1 + a


@public
def test2(a: uint256):
    pass
    """

    interface_codes = {
        'Folding': {
            'type': 'json',
            'code': [
                {
                    "name": "test",
                    "outputs": [{
                        "type": "uint256",
                        "name": "out"
                    }],
                    "inputs": [{
                        "type": "uint256",
                        "name": "s"
                    }],
                    "constant": False,
                    "payable": False,
                    "type": "function",
                },
                {
                    "name": "test2",
                    "outputs": [],
                    "inputs": [{
                        "type": "uint256",
                        "name": "s"
                    }],
                    "constant": False,
                    "payable": False,
                    "type": "function",
                }
            ]
        }
    }

    c = get_contract(code, interface_codes=interface_codes)

    assert c.test(2) == 3


def test_units_interface(w3, get_contract):
    code = """
import balanceof as BalanceOf

implements: BalanceOf

@public
@constant
def balanceOf(owner: address) -> wei_value:
    return as_wei_value(1, "ether")
    """
    interface_code = """
@public
@constant
def balanceOf(owner: address) -> uint256:
    pass
    """
    interface_codes = {
        "BalanceOf": {
            'type': 'vyper',
            'code': interface_code
        }
    }
    c = get_contract(code, interface_codes=interface_codes)

    assert c.balanceOf(w3.eth.accounts[0]) == w3.toWei(1, "ether")


def test_local_and_global_interface_namespaces():
    interface_code = """
@public
def foo() -> uint256:
    pass
    """

    global_interface_codes = {
        'FooInterface': {
            'type': 'vyper',
            'code': interface_code
        },
        'BarInterface': {
            'type': 'vyper',
            'code': interface_code
        }
    }
    local_interface_codes = {
        'FooContract': {
            'FooInterface': {
                'type': 'vyper',
                'code': interface_code
            },
        },
        'BarContract': {
            'BarInterface': {
                'type': 'vyper',
                'code': interface_code
            }
        }
    }

    code = """
import a as {0}

implements: {0}

@public
def foo() -> uint256:
    return 1
    """

    codes = {
        'FooContract': code.format('FooInterface'),
        'BarContract': code.format('BarInterface')
    }

    global_compiled = compile_codes(codes, interface_codes=global_interface_codes)
    local_compiled = compile_codes(codes, interface_codes=local_interface_codes)
    assert global_compiled == local_compiled


def test_self_interface_cannot_compile(assert_compile_failed):
    code = """
contract Bar:
    def foo() -> uint256: constant

@public
def foo() -> uint256 :
    return 42

@public
def bar() -> uint256:
    return Bar(self).foo()
"""
    assert_compile_failed(
        lambda: compile_code(code),
        StructureException
    )


def test_self_interface_via_storage_raises(get_contract, assert_tx_failed):
    code = """
contract Bar:
    def foo() -> uint256: constant

bar_contract: Bar

@public
def __init__():
    self.bar_contract = Bar(self)

@public
def foo() -> uint256 :
    return 42

@public
def bar() -> uint256:
    return self.bar_contract.foo()
    """
    c = get_contract(code)
    assert_tx_failed(lambda: c.bar())


def test_self_interface_via_calldata_raises(get_contract, assert_tx_failed):
    code = """
contract Bar:
    def foo() -> uint256: constant

@public
def foo() -> uint256 :
    return 42

@public
def bar(a: address) -> uint256:
    return Bar(a).foo()
    """
    c = get_contract(code)
    assert_tx_failed(lambda: c.bar(c.address))
