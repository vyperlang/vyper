import pytest

from vyper import compiler
from vyper.exceptions import StructureException, TypeMismatch

fail_list = [
    """
event Bar:
    _value: int128[4]

x: decimal[4]

@external
def foo():
    log Bar(self.x)
    """,
    """
event Bar:
    _value: int128[4]

@external
def foo():
    x: decimal[4] = [0.0, 0.0, 0.0, 0.0]
    log Bar(x)
    """,
    """
struct Foo:
    pass

@external
def foo():
    log Foo  # missing parens
    """,
    """
event Test:
    n: uint256

@external
def test():
    log Test(-7)
   """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_logging_fail(bad_code):
    with pytest.raises((TypeMismatch, StructureException)):
        compiler.compile_code(bad_code)


@pytest.mark.parametrize("mutability", ["@pure", "@view"])
@pytest.mark.parametrize("visibility", ["@internal", "@external"])
def test_logging_from_non_mutable(mutability, visibility):
    code = f"""
event Test:
    n: uint256

{visibility}
{mutability}
def test():
    log Test(1)
    """
    with pytest.raises(StructureException):
        compiler.compile_code(code)
