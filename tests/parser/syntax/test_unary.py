import pytest

from vyper.exceptions import UnimplementedException


def test_invert_decimal_fail(get_contract, assert_compile_failed):
    code = """
@external
def foo():
    a: decimal = ~2.5
    """
    assert_compile_failed(lambda: get_contract(code), UnimplementedException)
