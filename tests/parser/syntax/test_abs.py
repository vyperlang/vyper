import pytest

from vyper.exceptions import OverflowException


def test_abs_int256_bound(get_contract):
    code = """
@external
def foo() -> int256:
    return abs(-57896044618658097711785492504343953926634992332820282019728792003956564819967)
    """
    c = get_contract(code)
    assert c.foo() == 2 ** 255 - 1


BAD_CODE = [
    (
        """
@external
def foo() -> int256:
    return abs(-57896044618658097711785492504343953926634992332820282019728792003956564819968)
    """,
        OverflowException,  # (-2 ** 255) is out of range of int256 after folding
    ),
    (
        """
@external
def foo() -> int256:
    return abs(-115792089237316195423570985008687907853269984665640564039457584007913129639937)
    """,
        OverflowException,  # (-2 ** 256 - 1) is out of range of int256 before folding
    ),
]


@pytest.mark.parametrize("bad_code,exception", BAD_CODE)
def test_abs_invalid(get_contract, assert_compile_failed, bad_code, exception):
    assert_compile_failed(lambda: get_contract(bad_code), exception)
