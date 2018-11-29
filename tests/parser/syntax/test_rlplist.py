import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatchException, StructureException


fail_list = [
    """
@public
def foo() -> address:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[1]
    """,
    """
@public
def foo() -> address:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[2]
    """,
    """
@public
def foo() -> bytes[500]:
    x = RLPList('\xe1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', [bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes])
    return x[1]
    """,
    ("""
@public
def foo() -> bytes[500]:
    x: int128 = 1
    return RLPList('\xe0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
    """, StructureException),
    """
@public
def foo() -> bytes[500]:
    x: int128[3] = [1, 2, 3]
    return RLPList(x, [bytes])
    """,
    """
@public
def foo() -> bytes[500]:
    x: bytes[500] = '\xe1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    a: int128 = 1
    return RLPList(x, a)
    """,
    """
@public
def foo() -> bytes[500]:
    x: bytes[500] = '\xe1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    return RLPList(x, [])
    """,
    """
@public
def foo() -> bytes32:
    x = RLPList('\xe1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', [address, int128[2]])
    return x[1]
    """,
    """
@public
def foo() -> bytes32:
    x = RLPList('\xe1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', [decimal])
    return x[1]
    """,
    """
@public
def foo() -> bytes32:
    x = RLPList('\xe1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', [int128(wei)])
    return x[1]
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_rlplist_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatchException):
            compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo() -> bytes[500]:
    x = RLPList('\xe0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', [bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes])
    return x[1]
    """,
    """
@public
def foo() -> address:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[0]
    """,
    """
@public
def foo() -> bytes32:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[1]
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_rlplist_success(good_code):
    assert compiler.compile_code(good_code) is not None
