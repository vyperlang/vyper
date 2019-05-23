import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    VariableDeclarationException,
)

fail_list = [  # noqa: E122
"""
@public
def test1(b: uint256) -> uint256:
    a: uint256 = a + b
    return a
""",
"""
@public
def test2(b: uint256, c: uint256) -> uint256:
    a: uint256 = a + b + c
    return a
""",
"""
@public
def test3(b: uint256, c: uint256) -> uint256:
    a: uint256 = - a
    return a
""",
"""
@public
def test4(b: bool) -> bool:
    a: bool = b or a
    return a
""",
"""
@public
def test5(b: bool) -> bool:
    a: bool = a != b
    return a
""",
"""
@public
def test6(b:bool, c: bool) -> bool:
    a: bool = (a and b) and c
    return a
"""
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_type_exception(bad_code):
    with raises(VariableDeclarationException):
        compiler.compile_code(bad_code)
