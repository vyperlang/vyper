import pytest

from viper import compiler


valid_list = [
    """
def convert1(inp: bytes32) -> num256:
    return as_num256(inp)
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_as_wei_success(good_code):
    assert compiler.compile(good_code) is not None
