import pytest

from vyper.compiler import compile_code
from vyper.exceptions import (
    FunctionDeclarationException,
    InvalidLiteral,
    NonPayableViolation,
    StructureException,
    TypeMismatch,
)


def test_default_param_abi(get_contract):
    code = """
@public
@payable
def safeTransferFrom(_data: bytes[100] = b"test", _b: int128 = 1):
    pass
    """
    abi = get_contract(code)._classic_contract.abi

    assert len(abi) == 3
    assert set([fdef['name'] for fdef in abi]) == {'safeTransferFrom'}
    assert abi[0]['inputs'] == []
    assert abi[1]['inputs'] == [{'type': 'bytes', 'name': '_data'}]
    assert abi[2]['inputs'] == [
        {'type': 'bytes', 'name': '_data'},
        {'type': 'int128', 'name': '_b'},
    ]


def test_basic_default_param_passthrough(get_contract):
    code = """
@public
def fooBar(_data: bytes[100] = "test", _b: int128 = 1) -> int128:
    return 12321
    """

    c = get_contract(code)

    assert c.fooBar() == 12321
    assert c.fooBar(b"drum drum") == 12321
    assert c.fooBar(b"drum drum", 2) == 12321


def test_basic_default_param_set(get_contract):
    code = """
@public
def fooBar(a:int128, b: uint256 = 333) -> (int128, uint256):
    return a, b
    """

    c = get_contract(code)
    assert c.fooBar(456, 444) == [456, 444]
    assert c.fooBar(456) == [456, 333]


def test_basic_default_param_set_2args(get_contract):
    code = """
@public
def fooBar(a:int128, b: uint256 = 999, c: address = 0x0000000000000000000000000000000000000001) -> (int128, uint256, address):  # noqa: E501
    return a, b, c
    """

    c = get_contract(code)
    c_default_value = '0x0000000000000000000000000000000000000001'
    b_default_value = 999
    addr2 = '0x1000000000000000000000000000000000004321'

    # b default value, c default value
    assert c.fooBar(123) == [123, b_default_value, c_default_value]
    # c default_value, b set from param
    assert c.fooBar(456, 444) == [456, 444, c_default_value]
    # no default values
    assert c.fooBar(6789, 4567, addr2) == [6789, 4567, addr2]


def test_default_param_bytes(get_contract):
    code = """
@public
def fooBar(a: bytes[100], b: int128, c: bytes[100] = "testing", d: uint256 = 999) -> (bytes[100], int128, bytes[100], uint256):  # noqa: E501
    return a, b, c, d
    """
    c = get_contract(code)
    c_default = b"testing"
    d_default = 999

    # c set, 7d default value
    assert c.fooBar(b"booo", 12321, b'woo') == [b"booo", 12321, b'woo', d_default]
    # d set, c set
    assert c.fooBar(b"booo", 12321, b"lucky", 777) == [b"booo", 12321, b"lucky", 777]
    # no default values
    assert c.fooBar(b"booo", 12321) == [b"booo", 12321, c_default, d_default]


def test_default_param_array(get_contract):
    code = """
@public
def fooBar(a: bytes[100], b: uint256[2], c: bytes[6] = "hello", d: int128[3] = [6, 7, 8]) -> (bytes[100], uint256, bytes[6], int128):  # noqa: E501
    return a, b[1], c, d[2]
    """
    c = get_contract(code)
    c_default = b"hello"
    d_default = 8

    # c set, d default value
    assert c.fooBar(b"booo", [99, 88], b'woo') == [b"booo", 88, b'woo', d_default]
    # d set, c set
    assert c.fooBar(b"booo", [22, 11], b"lucky", [24, 25, 26]) == [b"booo", 11, b"lucky", 26]
    # no default values
    assert c.fooBar(b"booo", [55, 66]) == [b"booo", 66, c_default, d_default]


def test_default_param_clamp(get_contract, monkeypatch, assert_tx_failed):
    code = """
@public
def bar(a: int128, b: int128 = -1) -> (int128, int128):  # noqa: E501
    return a, b
    """

    c = get_contract(code)

    assert c.bar(-123) == [-123, -1]
    assert c.bar(100, 100) == [100, 100]

    def validate_value(cls, value):
        pass

    monkeypatch.setattr('eth_abi.encoding.NumberEncoder.validate_value', validate_value)

    assert c.bar(200, 2**127 - 1) == [200, 2**127 - 1]
    assert_tx_failed(lambda: c.bar(200, 2**127))


def test_default_param_private(get_contract):
    code = """
@private
def fooBar(a: bytes[100], b: uint256, c: bytes[20] = "crazy") -> (bytes[100], uint256, bytes[20]):
    return a, b, c

@public
def callMe() -> (bytes[100], uint256, bytes[20]):
    return self.fooBar(b'I just met you', 123456)

@public
def callMeMaybe() -> (bytes[100], uint256, bytes[20]):
    # return self.fooBar(b'here is my number', 555123456, b'baby')
    a: bytes[100] = b""
    b: uint256 = 0
    c: bytes[20] = b""
    a, b, c = self.fooBar(b'here is my number', 555123456, b'baby')
    return a, b, c
    """

    c = get_contract(code)

    # assert c.callMe() == [b'hello there', 123456, b'crazy']
    assert c.callMeMaybe() == [b'here is my number', 555123456, b'baby']


def test_builtin_constants_as_default(get_contract):
    code = """
@public
def foo(a: int128 = MIN_INT128, b: int128 = MAX_INT128) -> (int128, int128):
    return a, b
    """
    c = get_contract(code)
    assert c.foo() == [-(2**127), 2**127-1]
    assert c.foo(31337) == [31337, 2**127-1]
    assert c.foo(13, 42) == [13, 42]


def test_environment_vars_as_default(get_contract):
    code = """
xx: uint256

@public
@payable
def foo(a: uint256 = msg.value) -> bool:
    self.xx += a
    return True

@public
def bar() -> uint256:
    return self.xx

@public
def get_balance() -> uint256:
    return self.balance
    """
    c = get_contract(code)
    c.foo(transact={'value': 31337})
    assert c.bar() == 31337
    c.foo(666, transact={'value': 9001})
    assert c.bar() == 31337 + 666
    assert c.get_balance() == 31337 + 9001


PASSING_CONTRACTS = [
    """
@public
def foo(a: bool = True, b: bool[2] = [True, False]): pass
    """,
    """
@public
def foo(
    a: address = 0x0c04792e92e6b2896a18568fD936781E9857feB7,
    b: address[2] = [
        0x0c04792e92e6b2896a18568fD936781E9857feB7,
        0x0c04792e92e6b2896a18568fD936781E9857feB7
    ]): pass
    """,
    """
@public
def foo(a: uint256 = 12345, b: uint256[2] = [31337, 42]): pass
    """,
    """
@public
def foo(a: int128 = -31, b: int128[2] = [64, -46]): pass
    """,
    """
@public
def foo(a: bytes[6] = "potato"): pass
    """,
    """
@public
def foo(a: decimal = 3.14, b: decimal[2] = [1.337, 2.69]): pass
    """,
    """
@public
def foo(a: address = msg.sender, b: address[3] = [msg.sender, tx.origin, block.coinbase]): pass
    """,
    """
@public
@payable
def foo(a: uint256 = msg.value): pass
    """,
]


@pytest.mark.parametrize('code', PASSING_CONTRACTS)
def test_good_default_params(code):
    assert compile_code(code)


FAILING_CONTRACTS = [
    ("""
# default params must be literals
x: int128

@public
def foo(xx: int128, y: int128 = xx): pass
    """, FunctionDeclarationException),
    ("""
# value out of range for uint256
@public
def foo(a: uint256 = -1): pass
    """, InvalidLiteral),
    ("""
# value out of range for int128
@public
def foo(a: int128 = 170141183460469231731687303715884105728): pass
    """, InvalidLiteral),
    ("""
# value out of range for uint256 array
@public
def foo(a: uint256[2] = [13, -42]): pass
     """, InvalidLiteral),
    ("""
# value out of range for int128 array
@public
def foo(a: int128[2] = [12, 170141183460469231731687303715884105728]): pass
    """, TypeMismatch),
    ("""
# array type mismatch
@public
def foo(a: uint256[2] = [12, True]): pass
    """, TypeMismatch),
    ("""
# wrong length
@public
def foo(a: uint256[2] = [1, 2, 3]): pass
    """, TypeMismatch),
    ("""
# default params must be literals
x: uint256

@public
def foo(a: uint256 = self.x): pass
     """, FunctionDeclarationException),
    ("""
# default params must be literals inside array
x: uint256

@public
def foo(a: uint256[2] = [2, self.x]): pass
     """, FunctionDeclarationException),
    ("""
# msg.value in a nonpayable
@public
def foo(a: uint256 = msg.value): pass
""", NonPayableViolation),
    ("""
# msg.sender in a private function
@private
def foo(a: address = msg.sender): pass
    """, StructureException),
]


@pytest.mark.parametrize('failing_contract', FAILING_CONTRACTS)
def test_bad_default_params(failing_contract, assert_compile_failed):
    code, exc = failing_contract
    assert_compile_failed(lambda: compile_code(code), exc)
