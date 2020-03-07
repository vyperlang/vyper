from lark.exceptions import (
    UnexpectedToken,
)
import pytest
from pytest import (
    raises,
)

valid_dicts = [
    """
a = {a: b}
    """,
    """
a = {1: 2}
    """,
    """
{
    1: 2,
    3: 4
}
    """
]


@pytest.mark.parametrize('good_code', valid_dicts)
def test_grammar_good_dicts(good_code, lark_grammar):
    assert lark_grammar.parse(good_code + "\n")


invalid_dicts = [
    """
{**a}
    """,
    """
{*a}
    """,
    """
{1, 2, 3}
    """,
    """
{A}#
    """
]
@pytest.mark.parametrize('bad_code', invalid_dicts)
def test_grammar_bad_dicts(bad_code, lark_grammar):
    with raises(UnexpectedToken):
        assert lark_grammar.parse(bad_code + "\n")
