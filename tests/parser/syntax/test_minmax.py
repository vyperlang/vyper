import pytest

from vyper.exceptions import InvalidType, TypeMismatch

fail_list = [
    (
        """
@external
def foo():
    y: int128 = min(7, 0x1234567890123456789012345678901234567890)
    """,
        InvalidType,
    ),
    (
        """
@external
def foo():
    y: int256 = min(-1, max_value(int256) + 1)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo():
    y: int256 = min(-1, 57896044618658097711785492504343953926634992332820282019728792003956564819968)
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)
