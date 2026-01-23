import pytest

from vyper.compiler import compile_code

valid_list = [
    """
d: HashMap[uint256, HashMap[uint256, uint256]]

@external
def foo() -> uint256:
    return self.d[0][0]
    """,
    """
d: HashMap[uint256, uint256[10]]

@external
def foo() -> uint256:
    return self.d[0][0]
    """,
    """
d: HashMap[uint256, (uint256, uint256)]

@external
def foo() -> uint256:
    return self.d[0][0]
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_list_success(good_code):
    assert compile_code(good_code) is not None
