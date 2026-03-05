import pytest

from vyper.compiler import compile_code
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.exceptions import StaticAssertionException


def test_no_static_assert_legacy(get_contract, tx_failed):
    code = """
@external
def foo():
    assert 1 == 2
"""
    # without the flag, compile_code should raise StaticAssertionException
    settings = Settings(optimize=OptimizationLevel.GAS, experimental_codegen=False)
    with pytest.raises(StaticAssertionException):
        compile_code(code, output_formats=["bytecode"], settings=settings)

    # with the flag, it should compile but revert at runtime
    settings = Settings(
        optimize=OptimizationLevel.GAS, experimental_codegen=False, no_static_assert=True
    )
    c = get_contract(code, compiler_settings=settings)
    with tx_failed():
        c.foo()


def test_no_static_assert_underflow(get_contract, tx_failed):
    code = """
@external
def foo() -> uint256:
    x: uint256 = 0
    return x - 1
"""
    # without the flag, compile_code should raise StaticAssertionException
    settings = Settings(optimize=OptimizationLevel.GAS, experimental_codegen=True)
    with pytest.raises(StaticAssertionException):
        compile_code(code, output_formats=["bytecode"], settings=settings)

    # with the flag, it should compile but revert at runtime
    settings = Settings(
        optimize=OptimizationLevel.GAS, experimental_codegen=True, no_static_assert=True
    )
    c = get_contract(code, compiler_settings=settings)
    with tx_failed():
        c.foo()
