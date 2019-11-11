import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    FunctionDeclarationException,
    VariableDeclarationException,
)
from vyper.parser.expr import (
    BUILTIN_CONSTANTS,
    ENVIRONMENT_VARIABLES,
)

fail_list = [
    """
@public
def foo(max: int128) -> int128:
    return max
    """,
    """
@public
def foo(len: int128, sha3: int128) -> int128:
    return len+sha3
    """,
    """
@public
def foo(len: int128, keccak256: int128) -> int128:
    return len+keccak256
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_variable_naming_fail(bad_code):

    with raises(FunctionDeclarationException):
        compiler.compile_code(bad_code)


@pytest.mark.parametrize('constant', list(BUILTIN_CONSTANTS)+list(ENVIRONMENT_VARIABLES))
def test_reserved_keywords_memory(constant, get_contract, assert_compile_failed):
    code = f"""
@public
def test():
    {constant}: int128 = 31337
    """
    assert_compile_failed(lambda: get_contract(code), VariableDeclarationException)


@pytest.mark.parametrize('constant', list(BUILTIN_CONSTANTS)+list(ENVIRONMENT_VARIABLES))
def test_reserved_keywords_storage(constant, get_contract, assert_compile_failed):
    code = f"{constant}: int128"
    assert_compile_failed(lambda: get_contract(code), VariableDeclarationException)


@pytest.mark.parametrize('constant', list(BUILTIN_CONSTANTS)+list(ENVIRONMENT_VARIABLES))
def test_reserved_keywords_fn_args(constant, get_contract, assert_compile_failed):
    code = f"""
@public
def test({constant}: int128):
    pass
    """
    assert_compile_failed(lambda: get_contract(code), FunctionDeclarationException)
