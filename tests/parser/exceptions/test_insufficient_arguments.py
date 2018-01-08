import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import StructureException

fail_list = [
    """
@public
def foo() -> num:
    return as_wei_value(10)
"""
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_insufficient_arguments(bad_code):
    with raises(StructureException) as ex:
        compiler.compile(bad_code)
    assert "Not enough arguments for function: as_wei_value" in str(ex.value)
