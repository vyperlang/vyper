import pytest

from vyper.exceptions import (
    FunctionDeclarationException,
    VariableDeclarationException,
)
from vyper.functions import (
    BUILTIN_FUNCTIONS,
)
from vyper.parser.expr import (
    BUILTIN_CONSTANTS,
    ENVIRONMENT_VARIABLES,
)
from vyper.utils import (
    RESERVED_KEYWORDS,
)

ALL_RESERVED_KEYWORDS = sorted(
                                set(BUILTIN_CONSTANTS.keys())
                                .union(BUILTIN_FUNCTIONS)
                                .union(RESERVED_KEYWORDS)
                                .union(ENVIRONMENT_VARIABLES)
                            )


@pytest.mark.parametrize('constant', ALL_RESERVED_KEYWORDS)
def test_reserved_keywords_memory(constant, get_contract, assert_compile_failed):
    code = f"""
@public
def test():
    {constant}: int128 = 31337
    """
    assert_compile_failed(lambda: get_contract(code), VariableDeclarationException)


@pytest.mark.parametrize('constant', ALL_RESERVED_KEYWORDS)
def test_reserved_keywords_storage(constant, get_contract, assert_compile_failed):
    code = f"{constant}: int128"
    assert_compile_failed(lambda: get_contract(code), VariableDeclarationException)


@pytest.mark.parametrize('constant', ALL_RESERVED_KEYWORDS)
def test_reserved_keywords_fn_args(constant, get_contract, assert_compile_failed):
    code = f"""
@public
def test({constant}: int128):
    pass
    """
    assert_compile_failed(lambda: get_contract(code), FunctionDeclarationException)


@pytest.mark.parametrize('constant', ALL_RESERVED_KEYWORDS)
def test_reserved_keywords_fns(constant, get_contract, assert_compile_failed):
    code = f"""
@public
def {constant}(var: int128):
    pass
    """
    assert_compile_failed(lambda: get_contract(code), FunctionDeclarationException)
