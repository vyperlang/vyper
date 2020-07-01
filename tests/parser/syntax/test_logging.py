import pytest

from vyper import compiler
from vyper.exceptions import InvalidType, TypeMismatch

fail_list = [
    """
event Bar:
    _value: int128[4]

x: decimal[4]

@external
def foo():
    log Bar(self.x)
    """,
    """
event Bar:
    _value: int128[4]

@external
def foo():
    x: decimal[4] = [0.0, 0.0, 0.0, 0.0]
    log Bar(x)
    """,
    (
        """
event Test:
    n: uint256

@external
def test():
    log Test(-7)
   """,
        InvalidType,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_logging_fail(bad_code):

    if isinstance(bad_code, tuple):
        with pytest.raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with pytest.raises(TypeMismatch):
            compiler.compile_code(bad_code)
