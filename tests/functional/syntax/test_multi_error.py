import pytest

from vyper import compiler
from vyper.exceptions import SyntaxException, VyperException

# Code with 3 syntax errors on 3 different lines:
# 1. Incomplete assignment `x =`
# 2. Missing colon after `if True`
# 3. Invalid function name (missing parenthesis)
MULTI_ERROR_CODE = """
@external
def foo():
    x =
    if True
        pass
"""


def test_multi_syntax_errors():
    """Multiple syntax errors are collected and raised together."""
    with pytest.raises(VyperException) as exc_info:
        compiler.compile_code(MULTI_ERROR_CODE)

    msg = str(exc_info.value)
    assert "Compilation failed with the following errors:" in msg
    # Should contain at least 2 SyntaxException entries
    assert msg.count("SyntaxException") >= 2
