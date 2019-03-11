import pytest

from vyper import (
    compiler,
)

valid_list = [
    """
@private
def mkint() -> int128:
    return 1

@public
def test_zerovalent():
    if True:
        self.mkint()

@public
def test_valency_mismatch():
    if True:
        self.mkint()
    else:
        pass
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_conditional_return_code(good_code):
    assert compiler.compile_code(good_code) is not None
