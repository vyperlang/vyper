import pytest

from vyper import compiler


valid_list = [
    """
x: public(int128)
    """,
    """
x: public(int128(wei / sec))
y: public(int128(wei / sec ** 2))
z: public(int128(1 / sec))

@public
def foo() -> int128(sec ** 2):
    return self.x / self.y / self.z
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_public_success(good_code):
    assert compiler.compile(good_code) is not None
