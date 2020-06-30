import pytest

from vyper import compiler

valid_list = [
    """
x: public(int128)
    """,
    """
x: public(int128)
y: public(int128)
z: public(int128)

@external
def foo() -> int128:
    return self.x / self.y / self.z
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_public_success(good_code):
    assert compiler.compile_code(good_code) is not None
