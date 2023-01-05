import pytest

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
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(assert_compile_failed, get_contract, bad_code, exc):
    assert_compile_failed(lambda: get_contract(bad_code), exc)
