import pytest

from vyper.exceptions import UnimplementedException


@pytest.mark.parametrize("op", ["&", "|", "^"])
def test_bitwise_decimal_fail(get_contract, assert_compile_failed, op):
    code = f"""
@external
def foo():
    a: decimal = 1.5 {op} 2.5
    """
    assert_compile_failed(lambda: get_contract(code), UnimplementedException)
