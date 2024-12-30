import pytest

from vyper import compile_code
from vyper.exceptions import InvalidType

fail_list = [
    (
        """
@external
def foo():
    a: address = min_value(address)
    """,
        InvalidType,
    ),
    (
        """
@external
def foo():
    a: address = max_value(address)
    """,
        InvalidType,
    ),
    (
        """
FOO: constant(address) = min_value(address)

@external
def foo():
    a: address = FOO
    """,
        InvalidType,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)
