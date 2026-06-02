from pathlib import Path

import pytest

from vyper import compiler
from vyper.compiler.input_bundle import FileInput
from vyper.exceptions import SyntaxException, VyperException

# Code with 2 recoverable syntax errors on 2 different lines:
# 1. Incomplete assignment `x =`
# 2. Missing colon after `if True`
MULTI_ERROR_CODE = """
@external
def foo():
    x =
    if True
        pass
"""


def test_multi_syntax_errors_are_reported_in_source_order():
    """Multiple syntax errors are collected and raised together."""
    with pytest.raises(VyperException) as exc_info:
        compiler.compile_code(MULTI_ERROR_CODE)

    msg = str(exc_info.value)
    assert "Compilation failed with the following errors:" in msg
    assert msg.count("SyntaxException") == 2
    assert msg.index("line 4:7") < msg.index("line 5:11")
    assert "invalid syntax" in msg
    assert "expected ':'" in msg


def test_syntax_recovery_stops_when_no_progress_is_possible():
    code = """
@external
def foo():
    x =
"""

    with pytest.raises(SyntaxException) as exc_info:
        compiler.compile_code(code)

    msg = str(exc_info.value)
    assert "invalid syntax" in msg
    assert "expected an indented block" not in msg


def test_syntax_recovery_skips_indentation_cascade_errors():
    code = """
if True
    pass
"""

    with pytest.raises(SyntaxException) as exc_info:
        compiler.compile_code(code)

    msg = str(exc_info.value)
    assert "expected ':'" in msg
    assert "unexpected indent" not in msg


def test_multi_syntax_errors_include_resolved_path():
    path = Path("/tmp/multi_error_path_check.vy")
    file_input = FileInput(source_id=1, path=path, resolved_path=path, contents=MULTI_ERROR_CODE)

    with pytest.raises(VyperException) as exc_info:
        compiler.compile_from_file_input(file_input)

    assert "multi_error_path_check.vy:4" in str(exc_info.value)
