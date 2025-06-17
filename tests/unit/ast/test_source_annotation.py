import pytest

from vyper.utils import annotate_source_code, indent

TEST_TEXT = """
test
lines
to
indent
"""[
    1:-1
]


def test_indent_indents_text():
    assert (
        indent(TEST_TEXT, indent_chars="-", level=1)
        == """
-test
-lines
-to
-indent
"""[
            1:-1
        ]
    )
    assert (
        indent(TEST_TEXT, indent_chars=" ", level=4)
        == """
    test
    lines
    to
    indent
"""[
            1:-1
        ]
    )
    assert (
        indent(TEST_TEXT, indent_chars=[" ", "*", "-", "="], level=4)
        == """
    test
****lines
----to
====indent
"""[
            1:-1
        ]
    )


def test_indent_raises_value_errors():
    with pytest.raises(ValueError, match="Must provide indentation chars for each line"):
        indent(TEST_TEXT, indent_chars=[" "], level=1)

    with pytest.raises(ValueError, match="Unrecognized indentation characters value"):
        indent(TEST_TEXT, indent_chars=None, level=1)  # type: ignore


TEST_SOURCE_CODE = r"""
# Attempts to display the line and column of violating code.
class ParserException(Exception):
    def __init__(self, message='Error Message not found.', item=None):
        self.message = message
        self.lineno = None
        self.col_offset = None

        if isinstance(item, tuple):  # is a position.
            self.lineno, self.col_offset = item
        elif item and hasattr(item, 'lineno'):
            self.set_err_pos(item.lineno, item.col_offset)
            if hasattr(item, 'source_code'):
                self.source_code = item.source_code.splitlines()

    def set_err_pos(self, lineno, col_offset):
        if not self.lineno:
            self.lineno = lineno

            if not self.col_offset:
                self.col_offset = col_offset

    def __str__(self):
        output = self.message

        if self.lineno and hasattr(self, 'source_code'):

            output = f'line {self.lineno}: {output}\n{self.source_code[self.lineno -1]}'

            if self.col_offset:
                col = '-' * self.col_offset + '^'
                output += '\n' + col

        elif self.lineno is not None and self.col_offset is not None:
            output = f'line {self.lineno}:{self.col_offset} {output}'

        return output
"""[
    1:-1
]


def test_annotate_source_code_marks_positions_in_source_code():
    annotation = annotate_source_code(
        TEST_SOURCE_CODE, 22, col_offset=16, context_lines=0, line_numbers=False
    )
    assert (
        annotation
        == r"""
    def __str__(self):
----------------^
"""[
            1:-1
        ]
    )

    annotation = annotate_source_code(
        TEST_SOURCE_CODE, 22, col_offset=15, context_lines=1, line_numbers=False
    )
    assert (
        annotation
        == r"""

    def __str__(self):
---------------^
        output = self.message
"""[
            1:-1
        ]
    )

    annotation = annotate_source_code(
        TEST_SOURCE_CODE, 22, col_offset=20, context_lines=2, line_numbers=False
    )
    assert (
        annotation
        == r"""
                self.col_offset = col_offset

    def __str__(self):
--------------------^
        output = self.message

"""[
            1:-1
        ]
    )

    annotation = annotate_source_code(
        TEST_SOURCE_CODE, 1, col_offset=5, context_lines=3, line_numbers=True
    )
    assert (
        annotation
        == r"""
---> 1 # Attempts to display the line and column of violating code.
------------^
     2 class ParserException(Exception):
     3     def __init__(self, message='Error Message not found.', item=None):
     4         self.message = message
"""[
            1:-1
        ]
    )

    annotation = annotate_source_code(
        TEST_SOURCE_CODE, 36, col_offset=8, context_lines=4, line_numbers=True
    )
    assert (
        annotation
        == r"""
     32
     33         elif self.lineno is not None and self.col_offset is not None:
     34             output = f'line {self.lineno}:{self.col_offset} {output}'
     35
---> 36         return output
----------------^
"""[
            1:-1
        ]
    )

    annotation = annotate_source_code(
        TEST_SOURCE_CODE, 15, col_offset=8, context_lines=11, line_numbers=True
    )
    assert (
        annotation
        == r"""
      4         self.message = message
      5         self.lineno = None
      6         self.col_offset = None
      7
      8         if isinstance(item, tuple):  # is a position.
      9             self.lineno, self.col_offset = item
     10         elif item and hasattr(item, 'lineno'):
     11             self.set_err_pos(item.lineno, item.col_offset)
     12             if hasattr(item, 'source_code'):
     13                 self.source_code = item.source_code.splitlines()
     14
---> 15     def set_err_pos(self, lineno, col_offset):
----------------^
     16         if not self.lineno:
     17             self.lineno = lineno
     18
     19             if not self.col_offset:
     20                 self.col_offset = col_offset
     21
     22     def __str__(self):
     23         output = self.message
     24
     25         if self.lineno and hasattr(self, 'source_code'):
     26
"""[
            1:-1
        ]
    )

    annotation = annotate_source_code(
        TEST_SOURCE_CODE, 15, col_offset=None, context_lines=3, line_numbers=True
    )
    assert (
        annotation
        == r"""
     12             if hasattr(item, 'source_code'):
     13                 self.source_code = item.source_code.splitlines()
     14
---> 15     def set_err_pos(self, lineno, col_offset):
     16         if not self.lineno:
     17             self.lineno = lineno
     18
"""[
            1:-1
        ]
    )

    annotation = annotate_source_code(
        TEST_SOURCE_CODE, 15, col_offset=None, context_lines=2, line_numbers=False
    )
    assert (
        annotation
        == r"""
                self.source_code = item.source_code.splitlines()

    def set_err_pos(self, lineno, col_offset):
        if not self.lineno:
            self.lineno = lineno
"""[
            1:-1
        ]
    )


@pytest.mark.parametrize("bad_lineno", (-100, -1, 0, 45, 1000))
def test_annotate_source_code_raises_value_errors(bad_lineno):
    with pytest.raises(ValueError, match="Line number is out of range"):
        annotate_source_code(TEST_SOURCE_CODE, bad_lineno)
