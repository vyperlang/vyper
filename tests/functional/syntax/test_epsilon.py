import pytest

from vyper import compile_code
from vyper.exceptions import InvalidType

fail_list = [
    (
        """
FOO: constant(address) = epsilon(address)
    """,
        InvalidType,
    )
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)
