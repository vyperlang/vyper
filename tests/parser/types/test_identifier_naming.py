import pytest

from vyper.ast.folding import BUILTIN_CONSTANTS
from vyper.builtin_functions import BUILTIN_FUNCTIONS
from vyper.codegen.expr import ENVIRONMENT_VARIABLES
from vyper.exceptions import NamespaceCollision, StructureException, SyntaxException
from vyper.semantics.namespace import RESERVED_KEYWORDS
from vyper.utils import FUNCTION_WHITELIST

ALL_RESERVED_KEYWORDS = (
    set(BUILTIN_CONSTANTS.keys())
    .union(BUILTIN_FUNCTIONS)
    .union(RESERVED_KEYWORDS)
    .union(ENVIRONMENT_VARIABLES)
)


@pytest.mark.parametrize("constant", sorted(ALL_RESERVED_KEYWORDS))
def test_reserved_keywords_memory(constant, get_contract, assert_compile_failed):
    code = f"""
@external
def test():
    {constant}: int128 = 31337
    """
    assert_compile_failed(
        lambda: get_contract(code), (SyntaxException, StructureException, NamespaceCollision)
    )


@pytest.mark.parametrize("constant", sorted(ALL_RESERVED_KEYWORDS))
def test_reserved_keywords_storage(constant, get_contract, assert_compile_failed):
    code = f"{constant}: int128"
    assert_compile_failed(
        lambda: get_contract(code), (SyntaxException, StructureException, NamespaceCollision)
    )


@pytest.mark.parametrize("constant", sorted(ALL_RESERVED_KEYWORDS))
def test_reserved_keywords_fn_args(constant, get_contract, assert_compile_failed):
    code = f"""
@external
def test({constant}: int128):
    pass
    """
    assert_compile_failed(
        lambda: get_contract(code), (SyntaxException, StructureException, NamespaceCollision)
    )


RESERVED_KEYWORDS_NOT_WHITELISTED = sorted(ALL_RESERVED_KEYWORDS.difference(FUNCTION_WHITELIST))


@pytest.mark.parametrize("constant", sorted(RESERVED_KEYWORDS_NOT_WHITELISTED))
def test_reserved_keywords_fns(constant, get_contract, assert_compile_failed):
    code = f"""
@external
def {constant}(var: int128):
    pass
    """
    assert_compile_failed(
        lambda: get_contract(code), (SyntaxException, StructureException, NamespaceCollision)
    )
