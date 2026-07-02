import pytest

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


@pytest.mark.parametrize("typ", REPRESENTATIVE_TYPES, ids=repr)
def test_bottom_is_subtype_of_every_type(typ):
    assert BottomT().is_subtype_of(typ)
    assert typ.is_supertype_of(BottomT())


def test_bottom_reflexive():
    assert BottomT().is_subtype_of(BottomT())
    assert BottomT().is_supertype_of(BottomT())


@pytest.mark.parametrize("typ", REPRESENTATIVE_TYPES, ids=repr)
def test_bottom_is_strict_subtype(typ):
    # Bottom is the *sub*type, not the top type: it must NOT be a supertype
    # of any other type, else Bottom would be bidirectionally assignable.
    assert not BottomT().is_supertype_of(typ)
    assert not typ.is_subtype_of(BottomT())
