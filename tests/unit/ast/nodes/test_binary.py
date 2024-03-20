import pytest

from vyper import ast as vy_ast
from vyper.exceptions import SyntaxException


def test_binary_becomes_bytes():
    expected = vy_ast.parse_to_ast(
        """
def x():
    foo: Bytes[1] = b'\x01'
    """
    )
    mutated = vy_ast.parse_to_ast(
        """
def x():
    foo: Bytes[1] = 0b00000001
    """
    )

    assert expected == mutated


def test_binary_length():
    with pytest.raises(SyntaxException):
        vy_ast.parse_to_ast("foo: Bytes[1] = 0b01")
