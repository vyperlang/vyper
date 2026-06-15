import pytest

from vyper import compiler
from vyper.compiler.settings import Settings
from vyper.exceptions import (
    CodegenPanic,
    InvalidType,
    StructureException,
    TypeMismatch,
    UndeclaredDefinition,
)
from vyper.semantics.types import INF, BytesT, DArrayT, StringT
from vyper.semantics.types.infinity import WILDCARD, Inf, Wildcard
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


def test_wildcard_singleton():
    assert WILDCARD is Wildcard.WILDCARD


def test_wildcard_repr():
    assert repr(WILDCARD) == "..."
    assert repr(BytesT(WILDCARD)) == "Bytes[...]"
    assert repr(StringT(WILDCARD)) == "String[...]"
    assert repr(DArrayT(UINT256_T, WILDCARD)) == "DynArray[uint256, ...]"


def test_wildcard_from_annotation(build_node):
    node = build_node("Bytes[...]", is_interface=True)
    t = type_from_annotation(node)
    assert t.length is WILDCARD
    assert isinstance(t, BytesT)

    node = build_node("String[...]", is_interface=True)
    t = type_from_annotation(node)
    assert t.length is WILDCARD
    assert isinstance(t, StringT)


def test_dynarray_wildcard_from_annotation(build_node):
    node = build_node("DynArray[uint256, ...]", is_interface=True)
    t = type_from_annotation(node)
    assert t.length is WILDCARD
    assert isinstance(t, DArrayT)
    assert t.value_type == UINT256_T


def test_wildcard_rejected_outside_interface(build_node):
    with pytest.raises(InvalidType) as e:
        type_from_annotation(build_node("Bytes[...]"))
    assert e.value.message == "Wildcard length is only allowed in interfaces"

    with pytest.raises(InvalidType) as e:
        type_from_annotation(build_node("String[...]"))
    assert e.value.message == "Wildcard length is only allowed in interfaces"

    with pytest.raises(InvalidType) as e:
        type_from_annotation(build_node("DynArray[uint256, ...]"))
    assert e.value.message == "Wildcard length is only allowed in interfaces"


def test_wildcard_subtyping():
    # Wildcard matches anything bidirectionally
    assert BytesT(WILDCARD).compare_type(BytesT(10))
    assert BytesT(10).compare_type(BytesT(WILDCARD))
    assert BytesT(WILDCARD).compare_type(BytesT(INF))
    assert BytesT(INF).compare_type(BytesT(WILDCARD))
    assert BytesT(WILDCARD).compare_type(BytesT(WILDCARD))

    assert StringT(WILDCARD).compare_type(StringT(10))
    assert StringT(10).compare_type(StringT(WILDCARD))


def test_dynarray_wildcard_subtyping():
    assert DArrayT(UINT256_T, WILDCARD).compare_type(DArrayT(UINT256_T, 10))
    assert DArrayT(UINT256_T, 10).compare_type(DArrayT(UINT256_T, WILDCARD))
    assert DArrayT(UINT256_T, WILDCARD).compare_type(DArrayT(UINT256_T, INF))
    assert DArrayT(UINT256_T, INF).compare_type(DArrayT(UINT256_T, WILDCARD))


def test_wildcard_not_equal_to_inf():
    # WILDCARD and INF are distinct
    assert BytesT(WILDCARD) != BytesT(INF)
    assert StringT(WILDCARD) != StringT(INF)
    assert DArrayT(UINT256_T, WILDCARD) != DArrayT(UINT256_T, INF)


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
    # INF cannot be used as a static array length
    (
        """
@external
def foo(x: uint256[INF]):
    pass
    """,
        InvalidType,
    ),
    # Ellipsis cannot be used as a static array length
    (
        """
@external
def foo(x: uint256[...]):
    pass
    """,
        InvalidType,
    ),
    # Ellipsis is only allowed in interfaces, not in regular functions
    (
        """
@external
def foo(x: Bytes[...]):
    pass
    """,
        InvalidType,
    ),
    # Ellipsis return type not allowed outside interfaces
    (
        """
@external
def foo() -> Bytes[...]:
    return b""
    """,
        InvalidType,
    ),
    # Ellipsis in state variable not allowed
    (
        """
x: Bytes[...]
    """,
        InvalidType,
    ),
    # Unbounded sequence types are not supported inside structs
    (
        """
struct S:
    x: Bytes[INF]
    """,
        StructureException,
    ),
    # Unbounded sequence types are not supported inside custom errors
    (
        """
error E:
    x: Bytes[INF]
    """,
        StructureException,
    ),
    # Unbounded sequence types are not supported inside static arrays
    (
        """
@external
def foo(x: DynArray[uint256, INF][2]):
    pass
    """,
        StructureException,
    ),
    # Indexed event arguments only support value types and bytestrings
    (
        """
event E:
    x: indexed(DynArray[uint256, INF])
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_inf_fail(bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)


def test_dynarray_inf():
    code = """
a: DynArray[uint256, INF]

@external
def foo() -> DynArray[uint256, INF]:
    return self.a
    """
    with pytest.raises(StructureException):
        compiler.compile_code(code)


@pytest.mark.parametrize(
    "code",
    [
        """
@external
def foo(x: Bytes[INF]) -> Bytes[INF]:
    return abi_encode(x)
        """,
        """
@external
def foo(code: Bytes[INF]) -> address:
    return raw_create(code)
        """,
        """
@external
def foo(target: address, x: Bytes[INF]) -> address:
    return create_from_blueprint(target, x)
        """,
    ],
)
def test_inf_legacy_builtin_gates(code):
    with pytest.raises(StructureException):
        compiler.compile_code(code, settings=Settings(experimental_codegen=False))


def _compile_inf_bytestring_code(code, experimental_codegen):
    if experimental_codegen:
        compiler.compile_code(code)
    else:
        with pytest.raises(CodegenPanic):
            compiler.compile_code(code)


def test_inf_pure_param(experimental_codegen):
    code = """
@pure
@external
def foo(x: Bytes[INF]) -> Bytes[INF]:
    return x
    """
    _compile_inf_bytestring_code(code, experimental_codegen)


def test_inf_pure_param_string(experimental_codegen):
    code = """
@pure
@external
def foo(x: String[INF]) -> String[INF]:
    return x
    """
    _compile_inf_bytestring_code(code, experimental_codegen)


def test_inf_pure_return(experimental_codegen):
    code = """
@pure
@external
def foo() -> Bytes[INF]:
    return b""
    """
    _compile_inf_bytestring_code(code, experimental_codegen)


def test_inf_pure_local_var(experimental_codegen):
    code = """
@pure
@external
def foo() -> Bytes[INF]:
    x: Bytes[INF] = b""
    return x
    """
    _compile_inf_bytestring_code(code, experimental_codegen)


def test_inf_pure_internal(experimental_codegen):
    code = """
@pure
@internal
def _bar(x: Bytes[INF]) -> Bytes[INF]:
    return x

@pure
@external
def foo(x: Bytes[INF]) -> Bytes[INF]:
    return self._bar(x)
    """
    _compile_inf_bytestring_code(code, experimental_codegen)


def _compile_inf_dynarray_code(code, experimental_codegen):
    if experimental_codegen:
        compiler.compile_code(code)
    else:
        with pytest.raises(CodegenPanic):
            compiler.compile_code(code)


def test_dynarray_inf_pure(experimental_codegen):
    code = """
@pure
@external
def foo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """
    _compile_inf_dynarray_code(code, experimental_codegen)
