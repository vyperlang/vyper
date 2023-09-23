import pytest

from vyper.ast.identifiers import RESERVED_KEYWORDS
from vyper.builtins.functions import BUILTIN_FUNCTIONS
from vyper.codegen.expr import ENVIRONMENT_VARIABLES
from vyper.exceptions import NamespaceCollision, StructureException, SyntaxException
from vyper.semantics.types.primitives import AddressT

ALL_RESERVED_KEYWORDS = BUILTIN_FUNCTIONS | RESERVED_KEYWORDS | ENVIRONMENT_VARIABLES


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


SELF_NAMESPACE_MEMBERS = set(AddressT._type_members.keys())
DISALLOWED_FN_NAMES = SELF_NAMESPACE_MEMBERS | RESERVED_KEYWORDS
ALLOWED_FN_NAMES = ALL_RESERVED_KEYWORDS - DISALLOWED_FN_NAMES


@pytest.mark.parametrize("constant", sorted(ALLOWED_FN_NAMES))
def test_reserved_keywords_fns_pass(constant, get_contract, assert_compile_failed):
    code = f"""
@external
def {constant}(var: int128):
    pass
    """
    assert get_contract(code) is not None


@pytest.mark.parametrize("constant", sorted(DISALLOWED_FN_NAMES))
def test_reserved_keywords_fns_fail(constant, get_contract, assert_compile_failed):
    code = f"""
@external
def {constant}(var: int128):
    pass
    """
    assert_compile_failed(
        lambda: get_contract(code), (SyntaxException, StructureException, NamespaceCollision)
    )
