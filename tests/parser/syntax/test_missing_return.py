import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import StructureException


fail_list = [
	"""
@public
def foo() -> num:
	pass
	""",
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_missing_return(bad_code):
    with raises(StructureException):
        compiler.compile(bad_code)
