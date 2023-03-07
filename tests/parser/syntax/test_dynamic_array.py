import pytest

from vyper import compiler
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
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(assert_compile_failed, get_contract, bad_code, exc):
    assert_compile_failed(lambda: get_contract(bad_code), exc)


valid_list = [
    """
enum Foo:
    FE
    FI

bar: DynArray[Foo, 10]
    """,  # dynamic arrays of enums are allowed, but not static arrays
    """
bar: DynArray[Bytes[30], 10]
    """,  # dynamic arrays of bytestrings are allowed, but not static arrays
]


@pytest.mark.parametrize("good_code", valid_list)
def test_dynarray_pass(good_code):
    assert compiler.compile_code(good_code) is not None
