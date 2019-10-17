from vyper.exceptions import (
    TypeMismatchException,
)


def test_unary_sub_uint256(assert_compile_failed, get_contract):
    code = """@public
def negate(a: uint256) -> uint256:
    return -(a)
    """
    assert_compile_failed(lambda: get_contract(code), exception=TypeMismatchException)


def test_unary_sub_int128(get_contract, assert_tx_failed):
    code = """@public
def negate(a: int128) -> int128:
    return -(a)
    """
    c = get_contract(code)
    # This test should revert on overflow condition
    assert_tx_failed(lambda: c.negate(-2**127))
