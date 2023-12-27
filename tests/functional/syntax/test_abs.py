import pytest

from vyper import compiler
from vyper.exceptions import InvalidType

fail_list = [
    (
        """
@external
def foo():
    y: int256 = abs(
        -57896044618658097711785492504343953926634992332820282019728792003956564819968
    )
    """,
        InvalidType,
    )
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_abs_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)


valid_list = [
    """
FOO: constant(int256) = -3
BAR: constant(int256) = abs(FOO)

@external
def foo():
    a: int256 = BAR
    """
]


@pytest.mark.parametrize("code", valid_list)
def test_abs_pass(code):
    assert compiler.compile_code(code) is not None
