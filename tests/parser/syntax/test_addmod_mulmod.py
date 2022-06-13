import pytest

from vyper.exceptions import InvalidType, OverflowException

BAD_CODE = [
    (
        """
@external
def foo() -> uint256:
    return {}(
        1,
        2,
        115792089237316195423570985008687907853269984665640564039457584007913129639936
    )
    """,
        OverflowException,
    ),
    (
        """
@external
def foo() -> uint256:
    return {}(-1, 2, 3)
    """,
        InvalidType,
    ),
]


@pytest.mark.parametrize("bad_code,exception", BAD_CODE)
@pytest.mark.parametrize("fn_name", ["uint256_addmod", "uint256_mulmod"])
def test_modmath_invalid(get_contract, assert_compile_failed, bad_code, exception, fn_name):
    assert_compile_failed(lambda: get_contract(bad_code.format(fn_name)), exception)
