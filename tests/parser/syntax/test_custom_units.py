import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import (
    VariableDeclarationException,
    InvalidTypeException
)


fail_list = [
    """
units: 1
    """,
    """
units: {
    "cm": "centimeter"
}
    """,
    """
units: {
    "cm": 1
}
    """,
    """
units: {
    cm: "centimeter"
}
units: {
    km: "kilometer"
}
    """,
    """
units: {
    wei: "wei"
}
    """,
    """
units: {
    cm: 123
}
    """,
    """
units: {
    cm: "centimeter",
    cm: "kilometer"
}
    """,
    ("""
units: {
    cm: "centimeter",
}
@public
def test():
    a: int128(km)
    """, InvalidTypeException),
    """
units: {
    cm: "centimeter",
}
@public
def test():
    cm: int128
    """,
    ("""
units: {
    cm: "centimeter",
}
a: int128(km)
    """, InvalidTypeException),
    """
units: {
    cm: "centimeter",
}
cm: bytes[5]
    """,
    """
@public
def test():
    units: bytes[4]
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_custom_units_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile(bad_code[0])
    else:
        with raises(VariableDeclarationException):
            compiler.compile(bad_code)
