import pytest

from viper import compiler


valid_list = [
    """
x: public(num)
    """,
    """
x: public(num(wei / sec))
y: public(num(wei / sec ** 2))
z: public(num(1 / sec))

@public
def foo() -> num(sec ** 2):
    return self.x / self.y / self.z
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_public_success(good_code):
    assert compiler.compile(good_code) is not None
