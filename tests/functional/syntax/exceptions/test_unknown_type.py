import pytest

from vyper import compiler
from vyper.exceptions import UnknownType


def test_unknown_type_exception():
    code = """
@internal
def foobar(token: IERC20):
    pass
    """
    with pytest.raises(UnknownType) as e:
        compiler.compile_code(code)
    assert "(hint: )" not in str(e.value)
