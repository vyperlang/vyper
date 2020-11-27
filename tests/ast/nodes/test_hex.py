import pytest

from vyper import ast as vy_ast
from vyper.exceptions import InvalidLiteral

code_invalid_checksum = [
    """
foo: constant(address) = 0x6b175474e89094c44da98b954eedeac495271d0f
    """,
    """
foo: constant(address[1]) = [0x6b175474e89094c44da98b954eedeac495271d0f]
    """,
    """
@external
def foo():
    bar: address = 0x6b175474e89094c44da98b954eedeac495271d0f
    """,
    """
@external
def foo():
    bar: address[1] = [0x6b175474e89094c44da98b954eedeac495271d0f]
    """,
    """
@external
def foo():
    for i in [0x6b175474e89094c44da98b954eedeac495271d0f]:
        pass
    """,
]


@pytest.mark.parametrize("code", code_invalid_checksum)
def test_invalid_checksum(code):
    vyper_module = vy_ast.parse_to_ast(code)

    with pytest.raises(InvalidLiteral):
        vy_ast.validation.validate_literal_nodes(vyper_module)
