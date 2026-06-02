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

THREE_ERROR_CODE = """
@external
def foo():
    x =
    y =
    z =
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


def test_three_syntax_errors_are_reported_in_source_order():
    with pytest.raises(VyperException) as exc_info:
        compiler.compile_code(THREE_ERROR_CODE)

    msg = str(exc_info.value)
    assert msg.count("SyntaxException") == 3
    assert msg.index("line 4:7") < msg.index("line 5:7") < msg.index("line 6:7")
    assert "expected an indented block" not in msg


@pytest.mark.parametrize(
    "code, expected_lines, expected_errors",
    [
        (
            """
@external
def foo():
    x =
    pass

@external
def bar:
    pass
""",
            ("line 4:7", "line 8:7"),
            ("invalid syntax", "expected '('"),
        ),
        (
            """
@external
def foo():
    x =
    pass

@external
def bar():
    y =
    pass
""",
            ("line 4:7", "line 9:7"),
            ("invalid syntax", "invalid syntax"),
        ),
        (
            """
@external
def foo():
    x +=
    y =
    pass
""",
            ("line 4:8", "line 5:7"),
            ("invalid syntax", "invalid syntax"),
        ),
        (
            """
@external
def foo():
    assert
    y =
    pass
""",
            ("line 4:10", "line 5:7"),
            ("invalid syntax", "invalid syntax"),
        ),
        (
            """
import

@external
def foo():
    y =
    pass
""",
            ("line 2:6", "line 6:7"),
            ("invalid syntax", "invalid syntax"),
        ),
    ],
)
def test_recoverable_syntax_errors_are_collected(code, expected_lines, expected_errors):
    with pytest.raises(VyperException) as exc_info:
        compiler.compile_code(code)

    msg = str(exc_info.value)
    assert msg.count("SyntaxException") == len(expected_lines)
    for line in expected_lines:
        assert line in msg
    for first_line, second_line in zip(expected_lines, expected_lines[1:]):
        assert msg.index(first_line) < msg.index(second_line)
    for error in expected_errors:
        assert error in msg


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


@pytest.mark.parametrize(
    "code, expected_error, rejected_errors",
    [
        (
            """
@external
def foo:
    pass
""",
            "expected '('",
            ("SyntaxException:", "expected an indented block"),
        ),
        (
            """
@external
def 123foo():
    pass
""",
            "invalid decimal literal",
            ("SyntaxException:", "unexpected indent"),
        ),
        (
            """
if True
    pass

if False
    pass
""",
            "expected ':'",
            ("SyntaxException:", "unexpected indent"),
        ),
        (
            """
@external
def foo() -> uint256:
    return
    x =
    pass
""",
            "invalid syntax",
            ("SyntaxException:", "expected an indented block"),
        ),
    ],
)
def test_unrecoverable_syntax_errors_stop_before_downstream_noise(
    code, expected_error, rejected_errors
):
    with pytest.raises(SyntaxException) as exc_info:
        compiler.compile_code(code)

    msg = str(exc_info.value)
    assert expected_error in msg
    for rejected_error in rejected_errors:
        assert rejected_error not in msg


@pytest.mark.parametrize(
    "code, primary_error, cascade_error",
    [
        (
            """
if True
    pass
""",
            "expected ':'",
            "unexpected indent",
        ),
        (
            """
@external
def foo():
    if True
        pass
    if False
        pass
""",
            "expected ':'",
            "unindent does not match any outer indentation level",
        ),
    ],
)
def test_syntax_recovery_skips_indentation_cascade_errors(code, primary_error, cascade_error):
    with pytest.raises(SyntaxException) as exc_info:
        compiler.compile_code(code)

    msg = str(exc_info.value)
    assert primary_error in msg
    assert cascade_error not in msg


def test_syntax_recovery_raises_before_orphaned_pre_parser_metadata_asserts():
    code = """
@external
def foo():
    for i: uint256 in range(10)
        pass
"""

    with pytest.raises(SyntaxException) as exc_info:
        compiler.compile_code(code)

    msg = str(exc_info.value)
    assert "expected ':'" in msg
    assert "AssertionError" not in msg


def test_multi_syntax_errors_include_resolved_path():
    path = Path("/tmp/multi_error_path_check.vy")
    file_input = FileInput(source_id=1, path=path, resolved_path=path, contents=MULTI_ERROR_CODE)

    with pytest.raises(VyperException) as exc_info:
        compiler.compile_from_file_input(file_input)

    assert "multi_error_path_check.vy:4" in str(exc_info.value)


def test_multi_syntax_error_hints_are_preserved():
    code = """
from ethereum.ercs import IERC20Detailed

@external
def foo():
    x =
    staticcall ERC20(msg.sender).transfer(msg.sender, staticall IERC20Detailed(msg.sender).decimals())
"""

    with pytest.raises(VyperException) as exc_info:
        compiler.compile_code(code)

    msg = str(exc_info.value)
    assert msg.count("SyntaxException") == 2
    assert "did you mean `staticcall`?" in msg
