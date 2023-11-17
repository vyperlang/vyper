import pytest

from vyper import compiler
from vyper.exceptions import InvalidType

fail_list = [
    (
        """
@external
def foo():
    a: uint256 = pow_mod256(-1, -1)
    """,
        InvalidType,
    )
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_powmod_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)


valid_list = [
    """
FOO: constant(uint256) = 3
BAR: constant(uint256) = 5
BAZ: constant(uint256) = pow_mod256(FOO, BAR)
    """
]


@pytest.mark.parametrize("code", valid_list)
def test_powmod_pass(code):
    assert compiler.compile_code(code) is not None
