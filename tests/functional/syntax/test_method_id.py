import pytest

from vyper import compile_code
from vyper.exceptions import InvalidLiteral, InvalidType

fail_list = [
    (
        """
@external
def foo():
    a: Bytes[4] = method_id("bar ()")
    """,
        InvalidLiteral,
    ),
    (
        """
FOO: constant(Bytes[4]) = method_id(1)
    """,
        InvalidType,
    ),
    (
        """
FOO: constant(Bytes[4]) = method_id("bar ()")
    """,
        InvalidLiteral,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_method_id_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


valid_list = [
    """
FOO: constant(String[5]) = "foo()"
BAR: constant(Bytes[4]) = method_id(FOO)

@external
def foo(a: Bytes[4] = BAR):
    pass
    """
]


@pytest.mark.parametrize("code", valid_list)
def test_method_id_pass(code):
    assert compile_code(code) is not None
