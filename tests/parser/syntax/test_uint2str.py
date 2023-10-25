import pytest

from vyper import compiler


valid_list = [
    """
FOO: constant(uint256) = 3
BAR: constant(String[78]) = uint2str(FOO)
    """,
]


@pytest.mark.parametrize("code", valid_list)
def test_addmulmod_pass(code):
    assert compiler.compile_code(code) is not None