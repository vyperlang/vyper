import pytest

from vyper.utils import (
    indent,
)


TEST_TEXT = """
test
lines
to
indent
"""[1:-1]


def test_indent_indents_text():
    assert indent(TEST_TEXT, indent_chars='-', level=1) == """
-test
-lines
-to
-indent
"""[1:-1]
    assert indent(TEST_TEXT, indent_chars=' ', level=4) == """
    test
    lines
    to
    indent
"""[1:-1]
    assert indent(TEST_TEXT, indent_chars=[' ', '*', '-', '='], level=4) == """
    test
****lines
----to
====indent
"""[1:-1]


def test_indent_raises_value_errors():
    with pytest.raises(
        ValueError,
        match='Must provide indentation chars for each line',
    ):
        indent(TEST_TEXT, indent_chars=[' '], level=1)

    with pytest.raises(
        ValueError,
        match='Unrecognized indentation characters value',
    ):
        indent(TEST_TEXT, indent_chars=None, level=1)  # type: ignore
