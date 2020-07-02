import pytest

from vyper import compiler
from vyper.exceptions import FunctionDeclarationException

fail_list = [
    """
@external
def unmatched_tupl_length() -> (Bytes[8], int128, Bytes[8]):
    return "test", 123
    """
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_tuple_return_fail(bad_code):

    with pytest.raises(FunctionDeclarationException):
        compiler.compile_code(bad_code)
