import pytest

from vyper import compiler
from vyper.exceptions import InvalidType
from vyper.semantics.types import (
    INF,
    PRIMITIVE_TYPES,
    BoolT,
    BytesT,
    DArrayT,
    FlagT,
    HashMapT,
    SArrayT,
    StringT,
    StructT,
    TupleT,
)
from vyper.semantics.types.base import BottomT, VyperType
from vyper.semantics.types.shortcuts import UINT256_T

REPRESENTATIVE_TYPES = [t for t in PRIMITIVE_TYPES.values() if isinstance(t, VyperType)] + [
    BytesT(10),
    BytesT(INF),
    StringT(10),
    StringT(INF),
    SArrayT(UINT256_T, 3),
    DArrayT(UINT256_T, 5),
    DArrayT(UINT256_T, INF),
    HashMapT(UINT256_T, UINT256_T),
    TupleT([UINT256_T, BoolT()]),
    StructT("Foo", {"a": UINT256_T, "b": BoolT()}),
    FlagT("Roles", {"ADMIN": None, "USER": None}),
    DArrayT(BottomT(), 1),
]


def test_bottom_is_primitive_type():
    assert BottomT() in PRIMITIVE_TYPES.values()


@pytest.mark.parametrize("typ", REPRESENTATIVE_TYPES, ids=repr)
def test_bottom_is_subtype_of_every_type(typ):
    assert BottomT().is_subtype_of(typ)
    assert typ.is_supertype_of(BottomT())


@pytest.mark.parametrize("typ", REPRESENTATIVE_TYPES, ids=repr)
def test_bottom_is_strict_subtype(typ):
    # While Never is the universal subtype, it should only be a supertype of itself
    if typ == BottomT():
        assert BottomT().is_supertype_of(typ)
        assert typ.is_subtype_of(BottomT())
    else:
        assert not BottomT().is_supertype_of(typ)
        assert not typ.is_subtype_of(BottomT())


NEVER_IN_USER_PROGRAM_SOURCES = [
    "x: Never",
    """
def foo() -> Never:
    pass
""",
    """
def foo(x: Never):
    pass
""",
    """
def foo():
    x: Never = empty(uint256)
""",
    """
def foo() -> DynArray[Never, 5]:
    return []
""",
]


@pytest.mark.parametrize("code", NEVER_IN_USER_PROGRAM_SOURCES)
def test_never_rejected_in_user_program(code):
    with pytest.raises(InvalidType) as excinfo:
        compiler.compile_code(code)
    assert excinfo.value.message == "`Never` is not allowed in user programs."
