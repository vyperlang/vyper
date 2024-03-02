import pytest

from vyper import ast as vy_ast
from vyper import semantics
from vyper.exceptions import BadChecksumAddress, InvalidLiteral

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
]


@pytest.mark.parametrize("code", code_invalid_checksum)
def test_bad_checksum_address(code, dummy_input_bundle):
    vyper_module = vy_ast.parse_to_ast(code)

    with pytest.raises(BadChecksumAddress):
        semantics.validate_semantics(vyper_module, dummy_input_bundle)


code_invalid_literal = [
    """
foo: constant(bytes20) = 0x6b175474e89094c44da98b954eedeac495271d0F
    """,
    """
foo: constant(bytes4) = 0x12_34_56
    """,
]


@pytest.mark.parametrize("code", code_invalid_literal)
def test_invalid_literal(code, dummy_input_bundle):
    vyper_module = vy_ast.parse_to_ast(code)

    with pytest.raises(InvalidLiteral):
        vyper_module = vy_ast.parse_to_ast(code)
        semantics.validate_semantics(vyper_module, dummy_input_bundle)
