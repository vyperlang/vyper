import json

import pytest

from vyper import compiler
from vyper.compiler.settings import Settings
from vyper.exceptions import InvalidType, StructureException, TypeMismatch, UndeclaredDefinition
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
    # Unbounded sequence types are not supported inside events
    (
        """
event E:
    x: Bytes[INF]
    """,
        StructureException,
    ),
    (
        """
event E:
    x: String[INF]
    """,
        StructureException,
    ),
    (
        """
event E:
    x: indexed(Bytes[INF])
    """,
        StructureException,
    ),
    (
        """
event E:
    x: indexed(String[INF])
    """,
        StructureException,
    ),
    (
        """
event E:
    x: DynArray[uint256, INF]
    """,
        StructureException,
    ),
    (
        """
event E:
    x: indexed(DynArray[uint256, INF])
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
    (
        """
@external
def foo(x: Bytes[INF][3]):
    pass
    """,
        StructureException,
    ),
    # Unbounded sequence types are not supported in HashMap keys
    (
        """
a: HashMap[Bytes[INF], uint256]
    """,
        StructureException,
    ),
    (
        """
a: HashMap[String[INF], uint256]
    """,
        StructureException,
    ),
    (
        """
a: HashMap[uint256, HashMap[Bytes[INF], uint256]]
    """,
        StructureException,
    ),
    # Unbounded sequence types are not supported in HashMap values
    (
        """
a: HashMap[uint256, Bytes[INF]]
    """,
        StructureException,
    ),
    # Nested unbounded sequence types are not supported inside tuples.
    (
        """
@external
def foo(x: (Bytes[INF], uint256)) -> uint256:
    return x[1]
    """,
        StructureException,
    ),
    (
        """
@external
def foo(x: Bytes[INF]) -> Bytes[INF]:
    y: (Bytes[INF], uint256) = (x, 1)
    return y[0]
    """,
        StructureException,
    ),
    (
        """
@external
def foo(x: Bytes[INF]) -> ((Bytes[INF],), uint256):
    return (x,), 1
    """,
        StructureException,
    ),
    (
        """
@external
def foo(x: Bytes[INF]) -> Bytes[INF]:
    return abi_encode((x,))
    """,
        StructureException,
    ),
    (
        """
@external
def foo(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, (Bytes[INF],), unwrap_tuple=False)[0]
    """,
        StructureException,
    ),
    (
        """
C: constant(((Bytes[INF],), uint256)) = ((b"abc",), 1)

@external
def foo() -> Bytes[INF]:
    return C[0][0]
    """,
        StructureException,
    ),
    (
        """
interface I:
    def foo(x: (Bytes[INF], uint256)) -> uint256: view
    """,
        StructureException,
    ),
    (
        """
interface I:
    def foo() -> ((Bytes[INF],), uint256): view
    """,
        StructureException,
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
        "a: Bytes[INF]",
        "a: String[INF]",
        "a: DynArray[uint256, INF]",
        "a: transient(Bytes[INF])",
        "a: transient(String[INF])",
        "a: transient(DynArray[uint256, INF])",
        """
a: immutable(Bytes[INF])

@deploy
def __init__():
    a = b""
        """,
        """
a: immutable(String[INF])

@deploy
def __init__():
    a = ""
        """,
        """
a: immutable(DynArray[uint256, INF])

@deploy
def __init__():
    a = []
        """,
    ],
)
def test_inf_module_variable_locations_rejected(code):
    with pytest.raises(StructureException, match="Module variables cannot use unbounded"):
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))


@pytest.mark.parametrize(
    ("typ", "message"),
    [
        (
            "DynArray[Bytes[INF], INF]",
            "DynArray element types cannot contain unbounded sequence types",
        ),
        (
            "DynArray[DynArray[uint256, INF], INF]",
            "DynArray element types cannot contain unbounded sequence types",
        ),
        (
            "DynArray[Bytes[10], INF]",
            "DynArray\\[\\.\\.\\., INF\\] is only supported with ABI-static element types",
        ),
        (
            "DynArray[String[10], INF]",
            "DynArray\\[\\.\\.\\., INF\\] is only supported with ABI-static element types",
        ),
        (
            "DynArray[DynArray[uint256, 3], INF]",
            "DynArray\\[\\.\\.\\., INF\\] is only supported with ABI-static element types",
        ),
    ],
)
def test_inf_deferred_dynarray_shapes_rejected(typ, message):
    code = f"""
@external
def foo(x: {typ}):
    pass
    """
    with pytest.raises(StructureException, match=message):
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))


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
        """
@external
def foo(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF])
        """,
        """
@external
def foo(x: Bytes[INF]):
    print(x)
        """,
    ],
)
def test_inf_legacy_builtin_gates(code):
    with pytest.raises(StructureException):
        compiler.compile_code(code, settings=Settings(experimental_codegen=False))


def test_inf_print_rejects_nested_arg():
    code = """
@external
def foo(x: Bytes[INF]):
    print((x,))
    """
    with pytest.raises(StructureException):
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))


@pytest.mark.parametrize(
    "code",
    [
        """
@external
def foo(x: DynArray[uint256, INF]) -> Bytes[INF]:
    return convert(x, Bytes[INF])
        """,
        """
@external
def foo(x: DynArray[uint256, 5]) -> Bytes[INF]:
    return convert(x, Bytes[INF])
        """,
        """
@external
def foo(x: uint256) -> DynArray[uint256, INF]:
    return convert(x, DynArray[uint256, INF])
        """,
        """
@external
def foo(x: uint256) -> DynArray[uint256, 5]:
    return convert(x, DynArray[uint256, 5])
        """,
    ],
)
@pytest.mark.parametrize("exp_codegen", [False, True])
def test_convert_rejects_dynarray_source_or_target(code, exp_codegen):
    with pytest.raises(TypeMismatch):
        compiler.compile_code(code, settings=Settings(experimental_codegen=exp_codegen))


@pytest.mark.parametrize(
    "code",
    [
        """
@external
def foo(x: Bytes[INF]) -> uint256:
    return convert(x, uint256)
        """,
        """
@external
def foo(x: String[INF]) -> Bytes[INF]:
    return convert(x, Bytes[INF])
        """,
        """
@external
def foo() -> uint256:
    return convert(msg.data, uint256)
        """,
    ],
)
def test_inf_convert_legacy_requires_experimental_codegen(code):
    with pytest.raises(StructureException):
        compiler.compile_code(code, settings=Settings(experimental_codegen=False))


@pytest.mark.parametrize(
    "code",
    [
        """
@internal
def _unused(x: Bytes[INF]) -> Bytes[INF]:
    return x

@external
def foo() -> uint256:
    return 1
        """,
        """
@internal
def _unused() -> uint256:
    x: Bytes[INF] = b"abc"
    return 1

@external
def foo() -> uint256:
    return 1
        """,
    ],
)
def test_unused_inf_internal_legacy_requires_experimental_codegen(code):
    with pytest.raises(StructureException):
        compiler.compile_code(code, settings=Settings(experimental_codegen=False))


def test_expression_only_inf_legacy_requires_experimental_codegen():
    code = """
@external
def foo() -> uint256:
    return len(empty(Bytes[INF]))
    """
    with pytest.raises(StructureException):
        compiler.compile_code(code, settings=Settings(experimental_codegen=False))


def test_legacy_codegen_allows_bounded_local_user_type():
    code = """
struct Quote:
    value: uint256

@external
def foo() -> uint256:
    quotes: DynArray[Quote, 1] = []
    return len(quotes)
    """
    compiler.compile_code(code, settings=Settings(experimental_codegen=False))


def test_inf_constants_compile():
    settings = Settings(experimental_codegen=True)
    code = """
C1: constant(Bytes[INF]) = b"abc"
C2: constant(DynArray[uint256, INF]) = [1, 2, 3]
C3: constant((uint256, Bytes[INF])) = (1, b"abc")

@external
def bytes_value() -> Bytes[INF]:
    return C1

@external
def dynarray_value() -> DynArray[uint256, INF]:
    return C2

@external
def tuple_value() -> (uint256, Bytes[INF]):
    return C3
    """
    compiler.compile_code(code, settings=settings)


def _compile_inf_bytestring_code(code, experimental_codegen):
    if experimental_codegen:
        compiler.compile_code(code)
    else:
        with pytest.raises(StructureException):
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


def test_wildcard_return_dynamic_element_requires_expected_bound():
    rejected = """
interface I:
    def foo() -> DynArray[Bytes[10], ...]: view

@external
def f(a: address) -> uint256:
    return len(staticcall I(a).foo())
    """
    with pytest.raises(StructureException):
        compiler.compile_code(rejected, settings=Settings(experimental_codegen=True))

    accepted = """
interface I:
    def foo() -> DynArray[Bytes[10], ...]: view

@external
def f(a: address) -> DynArray[Bytes[10], 5]:
    return staticcall I(a).foo()
    """
    compiler.compile_code(accepted, settings=Settings(experimental_codegen=True))


def test_wildcard_tuple_interface_arg_rejects_inf_source():
    code = """
interface I:
    def foo(x: (Bytes[...], uint256)) -> uint256: view

@external
def f(a: address, x: Bytes[INF]) -> uint256:
    return staticcall I(a).foo((x, 1))
    """
    with pytest.raises(StructureException):
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))


def test_wildcard_tuple_return_member_access_compile():
    code = """
interface I:
    def foo() -> (Bytes[...], uint256): view

@external
def f(a: address) -> uint256:
    return len((staticcall I(a).foo())[0])
    """
    compiler.compile_code(
        code, output_formats=["bytecode"], settings=Settings(experimental_codegen=True)
    )


def test_wildcard_tuple_return_dynamic_element_requires_expected_bound():
    code = """
interface I:
    def foo() -> (uint256, DynArray[Bytes[10], ...]): view

@external
def f(a: address) -> uint256:
    return len((staticcall I(a).foo())[1])
    """
    with pytest.raises(StructureException):
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))


def test_imported_wildcard_event_rejects_inf_arg(make_input_bundle):
    abi = [
        {
            "anonymous": False,
            "inputs": [{"indexed": False, "name": "x", "type": "bytes"}],
            "name": "Foo",
            "type": "event",
        }
    ]
    code = """
import JSONInterface

@external
def emit(x: Bytes[INF]):
    log JSONInterface.Foo(x=x)
    """
    input_bundle = make_input_bundle({"JSONInterface.json": json.dumps(abi)})
    with pytest.raises(StructureException):
        compiler.compile_code(
            code, input_bundle=input_bundle, settings=Settings(experimental_codegen=True)
        )


def test_imported_wildcard_event_accepts_bounded_arg(make_input_bundle):
    abi = [
        {
            "anonymous": False,
            "inputs": [{"indexed": False, "name": "x", "type": "bytes"}],
            "name": "Foo",
            "type": "event",
        }
    ]
    code = """
import JSONInterface

@external
def emit(x: Bytes[10]):
    log JSONInterface.Foo(x=x)
    """
    input_bundle = make_input_bundle({"JSONInterface.json": json.dumps(abi)})
    compiler.compile_code(
        code,
        output_formats=["bytecode"],
        input_bundle=input_bundle,
        settings=Settings(experimental_codegen=True),
    )


def test_imported_wildcard_error_accepts_bounded_arg(make_input_bundle):
    abi = [{"inputs": [{"name": "x", "type": "bytes"}], "name": "Oops", "type": "error"}]
    code = """
import JSONInterface

@external
def boom(x: Bytes[10]):
    raise JSONInterface.Oops(x)
    """
    input_bundle = make_input_bundle({"JSONInterface.json": json.dumps(abi)})
    compiler.compile_code(
        code,
        output_formats=["bytecode"],
        input_bundle=input_bundle,
        settings=Settings(experimental_codegen=True),
    )


def test_imported_wildcard_error_rejects_inf_arg(make_input_bundle):
    abi = [{"inputs": [{"name": "x", "type": "bytes"}], "name": "Oops", "type": "error"}]
    code = """
import JSONInterface

@external
def boom(x: Bytes[INF]):
    raise JSONInterface.Oops(x)
    """
    input_bundle = make_input_bundle({"JSONInterface.json": json.dumps(abi)})
    with pytest.raises(StructureException):
        compiler.compile_code(
            code, input_bundle=input_bundle, settings=Settings(experimental_codegen=True)
        )


def _compile_inf_dynarray_code(code, experimental_codegen):
    if experimental_codegen:
        compiler.compile_code(code)
    else:
        with pytest.raises(StructureException):
            compiler.compile_code(code)


def test_dynarray_inf_pure(experimental_codegen):
    code = """
@pure
@external
def foo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """
    _compile_inf_dynarray_code(code, experimental_codegen)
