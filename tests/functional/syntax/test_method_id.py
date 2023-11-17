import pytest

from vyper import compiler
from vyper.exceptions import InvalidLiteral

fail_list = [
    (
        """
@external
def foo():
    a: Bytes[4] = method_id("bar ()")
    """,
        InvalidLiteral,
    )
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_method_id_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)


valid_list = [
    """
FOO: constant(String[5]) = "foo()"
BAR: constant(Bytes[4]) = method_id(FOO)

@external
def foo(a: Bytes[4] = BAR):
    pass
    """
]


@pytest.mark.parametrize("code", valid_list)
def test_method_id_pass(code):
    assert compiler.compile_code(code) is not None
