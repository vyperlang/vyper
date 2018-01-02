import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import VariableDeclarationException


valid_list = [
    """
@public
def test():
    a: num = 1
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_ann_assign_success(good_code):
    assert compiler.compile(good_code) is not None
