import pytest
from pytest import (
    raises,
)

from lark.exceptions import (
    UnexpectedToken,
)

valid_decorator_codes = [
    """
@public
def test() -> uint256:
    return 123
    """,
    """
@private
def test() -> uint256:
    return 123
    """,
    """
@constant
def test() -> uint256:
    return 123
    """,
    """
@nonreentrant("test")
def test() -> uint256:
    return 123
    """
]


@pytest.mark.parametrize('good_code', valid_decorator_codes)
def test_grammar_good_decorators(good_code, lark_grammar):
    assert lark_grammar.parse(good_code + "\n")


invalid_decorator_codes = [
    """
@test
def test():
    pass
    """,
    """
@test("sometext")
def test():
    pass
    """,
    """
@test(123, 123)
def test():
    pass
    """,
    """
@constant("key")
def test():
    pass
    """
]
@pytest.mark.parametrize('bad_code', invalid_decorator_codes)
def test_grammar_bad_decorators(bad_code, lark_grammar):
    with raises(UnexpectedToken):
        assert lark_grammar.parse(bad_code + "\n")
