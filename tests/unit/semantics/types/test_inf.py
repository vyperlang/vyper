import pytest

from vyper import compiler
from vyper.exceptions import CompilerPanic, TypeMismatch, UndeclaredDefinition
from vyper.semantics.types import INF, BytesT, DArrayT, StringT
from vyper.semantics.types.infinity import Inf
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.semantics.types.utils import type_from_annotation


def test_inf_singleton():
    assert INF is Inf.INF


def test_inf_repr():
    assert repr(INF) == "INF"
    assert repr(BytesT(INF)) == "Bytes[INF]"
    assert repr(StringT(INF)) == "String[INF]"


def test_dynarray_inf_repr():
    assert repr(DArrayT(UINT256_T, INF)) == "DynArray[uint256, INF]"


def test_valid_subtyping():
    # INF >= n (unbounded accepts bounded)
    assert BytesT(INF).compare_type(BytesT(10))
    assert StringT(INF).compare_type(StringT(10))
    # INF >= INF
    assert BytesT(INF).compare_type(BytesT(INF))
    assert StringT(INF).compare_type(StringT(INF))


def test_dynarray_valid_subtyping():
    # INF >= n (unbounded accepts bounded)
    assert DArrayT(UINT256_T, INF).compare_type(DArrayT(UINT256_T, 10))
    # INF >= INF
    assert DArrayT(UINT256_T, INF).compare_type(DArrayT(UINT256_T, INF))


def test_invalid_subtyping():
    # n < INF (bounded doesn't accept unbounded)
    assert not BytesT(10).compare_type(BytesT(INF))
    assert not StringT(10).compare_type(StringT(INF))


def test_dynarray_invalid_subtyping():
    # n < INF (bounded doesn't accept unbounded)
    assert not DArrayT(UINT256_T, 10).compare_type(DArrayT(UINT256_T, INF))


def test_from_annotation_inf(build_node):
    node = build_node("Bytes[INF]")
    t = type_from_annotation(node)
    assert t.length is INF
    assert isinstance(t, BytesT)

    node = build_node("String[INF]")
    t = type_from_annotation(node)
    assert t.length is INF
    assert isinstance(t, StringT)


def test_dynarray_from_annotation_inf(build_node):
    node = build_node("DynArray[uint256, INF]")
    t = type_from_annotation(node)
    assert t.length is INF
    assert isinstance(t, DArrayT)
    assert t.value_type == UINT256_T


fail_list = [
    # lowercase inf is not recognized (INF is the correct identifier)
    (
        """
@external
def foo(x: Bytes[inf]):
    pass
    """,
        UndeclaredDefinition,
    ),
    # lowercase inf in DynArray
    (
        """
@external
def foo(x: DynArray[uint256, inf]):
    pass
    """,
        UndeclaredDefinition,
    ),
    # INF in arithmetic (invalid) - TypeMismatch for arithmetic operations
    (
        """
@external
def foo(x: Bytes[INF + 1]):
    pass
    """,
        TypeMismatch,
    ),
    # INF subtraction (invalid)
    (
        """
@external
def foo(x: Bytes[INF - 1]):
    pass
    """,
        TypeMismatch,
    ),
    # DynArray INF addition (invalid)
    (
        """
@external
def foo(x: DynArray[uint256, INF + 1]):
    pass
    """,
        TypeMismatch,
    ),
    # DynArray INF subtraction (invalid)
    (
        """
@external
def foo(x: DynArray[uint256, INF - 1]):
    pass
    """,
        TypeMismatch,
    ),
    # INF as a value expression
    (
        """
@external
def foo():
    x: uint256 = INF
    """,
        TypeMismatch,
    ),
    # INF in a return statement
    (
        """
@external
def foo() -> uint256:
    return INF
    """,
        TypeMismatch,
    ),
    # INF as a constant value
    (
        """
X: constant(uint256) = INF
    """,
        TypeMismatch,
    ),
    # INF as a function argument
    (
        """
@internal
def bar(x: uint256):
    pass

@external
def foo():
    self.bar(INF)
    """,
        TypeMismatch,
    ),
    # INF as a default parameter value
    (
        """
@external
def foo(x: uint256 = INF):
    pass
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_inf_fail(bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)


@pytest.mark.xfail(raises=CompilerPanic)
def test_inf_in_static_array():
    """INF cannot be used as a static array length"""
    code = """
@external
def foo(x: uint256[INF]):
    pass
    """
    compiler.compile_code(code)


@pytest.mark.xfail(raises=CompilerPanic)
def test_dynarray_inf():
    code = """
a: DynArray[uint256, INF]

@external
def foo() -> DynArray[uint256, INF]:
    return self.a
    """
    compiler.compile_code(code)
