import pytest

from tests.evm_backends.base_env import EvmError
from vyper.compiler import compile_code
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.exceptions import StaticAssertionException


def test_disable_static_exceptions_legacy(get_contract, tx_failed):
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
        optimize=OptimizationLevel.GAS, experimental_codegen=False, disable_static_exceptions=True
    )
    c = get_contract(code, compiler_settings=settings)
    with tx_failed():
        c.foo()


def test_disable_static_exceptions_underflow(get_contract, tx_failed):
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
        optimize=OptimizationLevel.GAS, experimental_codegen=True, disable_static_exceptions=True
    )
    c = get_contract(code, compiler_settings=settings)
    with tx_failed():
        c.foo()


STATIC_ASSERT_FALSE_STATEMENTS = [
    "assert False",
    "assert False, UNREACHABLE",
    "assert 1 == 2",
    "assert X",
    "assert not True",
    "assert empty(bool)",
]


@pytest.mark.parametrize("venom", [True, False])
@pytest.mark.parametrize("stmt", STATIC_ASSERT_FALSE_STATEMENTS)
def test_static_assert_false(stmt, venom, env, get_contract, tx_failed):
    code = f"""
X: constant(bool) = False

@external
def foo():
    {stmt}
"""
    if "UNREACHABLE" in stmt:
        failure = dict(exception=EvmError, exc_text=env.invalid_opcode_error)
    else:
        failure = {}

    # both pipelines reject an assertion which is known to fail
    settings = Settings(optimize=OptimizationLevel.GAS, experimental_codegen=venom)
    with pytest.raises(StaticAssertionException):
        compile_code(code, output_formats=["bytecode"], settings=settings)

    # with the flag, it should compile but revert at runtime
    settings = Settings(
        optimize=OptimizationLevel.GAS, experimental_codegen=venom, disable_static_exceptions=True
    )
    c = get_contract(code, compiler_settings=settings)
    with tx_failed(**failure):
        c.foo()

    # neither pipeline raises static exceptions at -O none
    settings = Settings(optimize=OptimizationLevel.NONE, experimental_codegen=venom)
    c = get_contract(code, compiler_settings=settings)
    with tx_failed(**failure):
        c.foo()


@pytest.mark.parametrize("venom", [True, False])
@pytest.mark.parametrize(
    "stmt",
    [
        # asserts with a reason are not static assertions
        'assert False, "reason"',
        'assert X, "reason"',
        # not constant
        "assert a != a",
        "assert True",
    ],
)
def test_static_assert_false_not_raised(stmt, venom):
    code = f"""
X: constant(bool) = False

@external
def foo(a: uint256):
    {stmt}
"""
    settings = Settings(optimize=OptimizationLevel.GAS, experimental_codegen=venom)
    compile_code(code, output_formats=["bytecode"], settings=settings)
