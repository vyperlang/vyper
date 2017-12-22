import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import VariableDeclarationException


fail_list = [
    """
@public
def test():
    a = 1
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_ann_assign_fail(bad_code):

    with raises(VariableDeclarationException):
        compiler.compile(bad_code)
