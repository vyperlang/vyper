import pytest

from vyper import compiler
from vyper.exceptions import (
    InstantiationException,
    InvalidAttribute,
    StructureException,
    TypeMismatch,
    UnknownAttribute,
)

fail_list = [
    """
event Bar:
    _value: int128[4]

x: decimal[4]

@external
def foo():
    log Bar(_value=self.x)
    """,
    """
event Bar:
    _value: int128[4]

@external
def foo():
    x: decimal[4] = [0.0, 0.0, 0.0, 0.0]
    log Bar(_value=x)
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
    log Test(n=-7)
   """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_logging_fail(bad_code):
    with pytest.raises((TypeMismatch, StructureException)):
        compiler.compile_code(bad_code)


def test_logging_fail_mixed_positional_kwargs():
    code = """
event Test:
    n: uint256
    o: uint256

@external
def test():
    log Test(7, o=12)
    """
    with pytest.raises(InstantiationException):
        compiler.compile_code(code)


def test_logging_fail_unknown_kwarg():
    code = """
event Test:
    n: uint256

@external
def test():
    log Test(n=7, o=12)
    """
    with pytest.raises(UnknownAttribute):
        compiler.compile_code(code)


def test_logging_fail_missing_kwarg():
    code = """
event Test:
    n: uint256
    o: uint256

@external
def test():
    log Test(n=7)
    """
    with pytest.raises(InstantiationException):
        compiler.compile_code(code)


def test_logging_fail_kwargs_out_of_order():
    code = """
event Test:
    n: uint256
    o: uint256

@external
def test():
    log Test(o=12, n=7)
    """
    with pytest.raises(InvalidAttribute):
        compiler.compile_code(code)


@pytest.mark.parametrize("mutability", ["@pure", "@view"])
@pytest.mark.parametrize("visibility", ["@internal", "@external"])
def test_logging_from_non_mutable(mutability, visibility):
    code = f"""
event Test:
    n: uint256

{visibility}
{mutability}
def test():
    log Test(n=1)
    """
    with pytest.raises(StructureException):
        compiler.compile_code(code)


def test_logging_with_positional_args(get_contract, get_logs):
    # TODO: Remove when positional arguments are fully deprecated
    code = """
event Test:
    n: uint256

@external
def test():
    log Test(1)
    """
    c = get_contract(code)
    c.test()
    (log,) = get_logs(c, "Test")
    assert log.args.n == 1
