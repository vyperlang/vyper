import pytest

from vyper import ast as vy_ast
from vyper import semantics
from vyper.exceptions import InvalidLiteral

code_invalid_checksum = [
    """
foo: constant(address) = 0x6b175474e89094c44da98b954eedeac495271d0F
    """,
    """
foo: constant(address[1]) = [0x6b175474e89094c44da98b954eedeac495271d0F]
    """,
    """
@external
def foo():
    bar: address = 0x6b175474e89094c44da98b954eedeac495271d0F
    """,
    """
@external
def foo():
    bar: address[1] = [0x6b175474e89094c44da98b954eedeac495271d0F]
    """,
    """
@external
def foo():
    for i: address in [0x6b175474e89094c44da98b954eedeac495271d0F]:
        pass
    """,
    """
foo: constant(bytes20) = 0x6b175474e89094c44da98b954eedeac495271d0F
    """,
    """
foo: constant(bytes4) = 0x12_34_56
    """,
]


@pytest.mark.parametrize("code", code_invalid_checksum)
def test_invalid_checksum(code, dummy_input_bundle):
    with pytest.raises(InvalidLiteral):
        vyper_module = vy_ast.parse_to_ast(code)
        semantics.analyze_module(vyper_module, dummy_input_bundle)
