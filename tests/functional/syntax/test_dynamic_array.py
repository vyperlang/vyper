import pytest

from vyper import compile_code
from vyper.exceptions import StructureException

fail_list = [
    (
        """
foo: DynArray[HashMap[uint8, uint8], 2]
    """,
        StructureException,
    ),
    (
        """
foo: public(DynArray[HashMap[uint8, uint8], 2])
    """,
        StructureException,
    ),
    (
        """
@external
def foo():
    a: DynArray = [1, 2, 3]
    """,
        StructureException,
    ),
    (
        """
@external
def foo():
    a: DynArray[uint256, FOO] = [1, 2, 3]
    """,
        StructureException,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


valid_list = [
    """
flag Foo:
    FE
    FI

bar: DynArray[Foo, 10]
    """,  # dynamic arrays of flags are allowed, but not static arrays
    """
bar: DynArray[Bytes[30], 10]
    """,  # dynamic arrays of bytestrings are allowed, but not static arrays
    """
@external
def bar():
    d: DynArray[uint256, 10] = []
    i: DynArray[uint256, 30] = d
    """,  # dynamic arrays can be assigned to others of larger size
    """
@external
def bar():
    d: DynArray[DynArray[uint256, 10], 10] = [[]]
    for i: DynArray[uint256, 30] in d:
        pass
    """,  # dynamic arrays can be assigned to others of larger size
]


@pytest.mark.parametrize("good_code", valid_list)
def test_dynarray_pass(good_code):
    assert compile_code(good_code) is not None
