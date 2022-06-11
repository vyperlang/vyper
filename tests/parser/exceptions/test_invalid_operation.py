import pytest

from vyper import compiler
from vyper.exceptions import InvalidOperation

fail_list = [
    """
@external
def foo():
    int128 = 5
    """
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_variable_declaration_exception(bad_code):
    with pytest.raises(InvalidOperation):
        compiler.compile_code(bad_code)
