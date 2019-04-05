import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    StructureException,
)

fail_list = [
    """
@public
def foo() -> int128:
    pass
    """,
    """
@public
def foo() -> int128:
    if False:
        return 123
    """,
    """
@public
def test() -> int128:
    if 1 == 1 :
        return 1
        if True:
            return 0
    else:
        assert False
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_missing_return(bad_code):
    with raises(StructureException):
        compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo() -> int128:
    return 123
    """,
    """
@public
def foo() -> int128:
    if False:
        return 123
    return 333
    """,
    """
@public
def test() -> int128:
    if 1 == 1 :
        return 1
    else:
        assert False
        return 0
    """,
    """
@public
def test() -> int128:
    x: bytes32
    if False:
        return 0
    else:
        x = sha3(x)
        return 1
        if False:
            return 1
    return 1
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_return_success(good_code):
    assert compiler.compile_code(good_code) is not None
