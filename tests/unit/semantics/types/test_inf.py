import json

import pytest

from vyper import compiler
from vyper.compiler.settings import Settings
from vyper.exceptions import (
    InvalidType,
    StateAccessViolation,
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


# events and custom errors are only ever ABI-encoded into a buffer, like
# external INF returns, so their top-level members may be unbounded
@pytest.mark.parametrize(
    "code",
    [
        """
event E:
    x: Bytes[INF]
    """,
        """
event E:
    x: String[INF]
    """,
        """
event E:
    x: indexed(Bytes[INF])
    """,
        """
event E:
    x: indexed(String[INF])
    """,
        """
event E:
    x: DynArray[uint256, INF]
    """,
        """
error E:
    x: Bytes[INF]
    """,
        """
error E:
    x: DynArray[uint256, INF]
    """,
    ],
)
def test_inf_event_and_error_members(compile_inf_code, code):
    compile_inf_code(code)


@pytest.mark.parametrize(
    "code",
    [
        """
event E:
    x: Bytes[10]

@external
def emit(x: Bytes[INF]):
    log E(x=x)
    """,
        """
error E:
    x: Bytes[10]

@external
def boom(x: Bytes[INF]):
    raise E(x)
    """,
    ],
)
def test_bounded_event_and_error_members_reject_inf_arg(code):
    with pytest.raises(TypeMismatch) as e:
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))
    assert e.value.message == "Given reference has type Bytes[INF], expected Bytes[10]"


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (
            """
event E:
    x: (Bytes[INF], uint256)
            """,
            "Event members cannot contain unbounded sequence types inside aggregate types",
        ),
        (
            """
error Oops:
    x: (Bytes[INF], uint256)
            """,
            "Custom error members cannot contain unbounded sequence types inside aggregate types",
        ),
    ],
)
def test_event_and_error_members_reject_nested_inf(code, message):
    # tuples are the only aggregate whose INF members survive type
    # construction; static and dynamic arrays reject them earlier
    with pytest.raises(StructureException) as e:
        compiler.compile_code(code)
    assert e.value.message == message


def test_event_rejects_nested_inf_list_arg():
    code = """
event E:
    xs: DynArray[Bytes[10], 3]

@external
def emit(x: Bytes[INF]):
    log E(xs=[x])
    """
    with pytest.raises(TypeMismatch) as e:
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))
    assert e.value.message == (
        "Expected DynArray[Bytes[10], 3] but literal can only be cast as "
        "Bytes[INF][1] or DynArray[Bytes[INF], 1]."
    )


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
    with pytest.raises(StructureException) as e:
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))
    assert e.value.message == "Module variables cannot use unbounded sequence types"


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
            "DynArray[..., INF] is only supported with ABI-static element types",
        ),
        (
            "DynArray[String[10], INF]",
            "DynArray[..., INF] is only supported with ABI-static element types",
        ),
        (
            "DynArray[DynArray[uint256, 3], INF]",
            "DynArray[..., INF] is only supported with ABI-static element types",
        ),
    ],
)
def test_inf_deferred_dynarray_shapes_rejected(typ, message):
    code = f"""
@external
def foo(x: {typ}):
    pass
    """
    with pytest.raises(StructureException) as e:
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))
    assert e.value.message == message


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
def test_inf_builtin_args(compile_inf_code, code):
    compile_inf_code(code)


def test_inf_print_rejects_nested_arg():
    code = """
@external
def foo(x: Bytes[INF]):
    print((x,))
    """
    with pytest.raises(StructureException) as e:
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))
    message = "print arguments cannot contain unbounded sequence types inside aggregate types"
    assert e.value.message == message


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (
            """
@external
def foo(x: DynArray[uint256, INF]) -> Bytes[INF]:
    return convert(x, Bytes[INF])
        """,
            "Can't convert DynArray[uint256, INF] to Bytes[INF]",
        ),
        (
            """
@external
def foo(x: DynArray[uint256, 5]) -> Bytes[INF]:
    return convert(x, Bytes[INF])
        """,
            "Can't convert DynArray[uint256, 5] to Bytes[INF]",
        ),
        (
            """
@external
def foo(x: uint256) -> DynArray[uint256, INF]:
    return convert(x, DynArray[uint256, INF])
        """,
            "Can't convert uint256 to DynArray[uint256, INF]",
        ),
        (
            """
@external
def foo(x: uint256) -> DynArray[uint256, 5]:
    return convert(x, DynArray[uint256, 5])
        """,
            "Can't convert uint256 to DynArray[uint256, 5]",
        ),
    ],
)
def test_convert_rejects_dynarray_source_or_target(code, message):
    with pytest.raises(TypeMismatch) as e:
        compiler.compile_code(code)
    assert e.value.message == message


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
def test_inf_convert(compile_inf_code, code):
    compile_inf_code(code)


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
def test_unused_inf_internal(compile_inf_code, code):
    compile_inf_code(code)


def test_expression_only_inf(compile_inf_code):
    code = """
@external
def foo() -> uint256:
    return len(empty(Bytes[INF]))
    """
    compile_inf_code(code)


@pytest.mark.parametrize(
    "code",
    [
        """
@external
def foo(x: address) -> bytes32:
    return keccak256(x.code)
        """,
        """
@external
def foo(x: address) -> Bytes[32]:
    return raw_call(0x0000000000000000000000000000000000000004, x.code, max_outsize=32)
        """,
        """
interface Foo:
    def f() -> Bytes[...]: view

@external
def bar(a: address) -> uint256:
    return len(staticcall Foo(a).f())
        """,
        """
interface Foo:
    def f() -> Bytes[...]: nonpayable

@external
def bar(a: address) -> Bytes[2]:
    return slice(extcall Foo(a).f(), 0, 2)
        """,
        """
interface Foo:
    def f() -> Bytes[...]: view

@external
def bar(a: address) -> Bytes[2]:
    return slice(staticcall Foo(a).f(), 0, 2)
        """,
    ],
)
def test_inf_valued_expression(compile_inf_code, code):
    compile_inf_code(code)


def test_json_abi_extcall_slice(compile_inf_code, make_input_bundle):
    # bytes returns from JSON ABI interfaces resolve to Bytes[INF] at the
    # call site; legacy codegen has no lowering for the resulting value
    abi = [
        {
            "inputs": [],
            "name": "returns_bytes",
            "outputs": [{"name": "", "type": "bytes"}],
            "stateMutability": "nonpayable",
            "type": "function",
        }
    ]
    code = """
import JSONInterface

@external
def foo(x: JSONInterface) -> Bytes[2]:
    return slice(extcall x.returns_bytes(), 0, 2)
    """
    input_bundle = make_input_bundle({"JSONInterface.json": json.dumps(abi)})
    compile_inf_code(code, input_bundle=input_bundle)


@pytest.mark.parametrize(
    "code",
    [
        """
@external
def foo() -> uint256:
    return len(msg.data)
        """,
        """
@external
def foo() -> Bytes[4]:
    return slice(msg.data, 0, 4)
        """,
        """
@external
def foo(x: address) -> Bytes[4]:
    return slice(x.code, 0, 4)
        """,
        """
@external
def foo() -> Bytes[4]:
    return slice(self.code, 0, 4)
        """,
        """
@external
@payable
def foo(target: address) -> Bytes[32]:
    return raw_call(target, msg.data, max_outsize=32)
        """,
    ],
)
def test_adhoc_bytes_sources_allowed_in_legacy(code):
    # msg.data, self.code and <address>.code have special legacy lowerings
    # inside len()/slice()/raw_call() which never materialize an unbounded
    # sequence value
    compiler.compile_code(code, settings=Settings(experimental_codegen=False))


def test_exported_inf_function(compile_inf_code, make_input_bundle):
    lib = """
@external
def foo() -> uint256:
    x: Bytes[INF] = b"hi"
    return len(x)
    """
    code = """
import lib

exports: lib.foo
    """
    input_bundle = make_input_bundle({"lib.vy": lib})
    compile_inf_code(code, input_bundle=input_bundle)


def test_imported_inf_function_call(compile_inf_code, make_input_bundle):
    lib = """
@internal
def helper() -> uint256:
    x: Bytes[INF] = b"hi"
    return len(x)
    """
    code = """
import lib

@external
def foo() -> uint256:
    return lib.helper()
    """
    input_bundle = make_input_bundle({"lib.vy": lib})
    compile_inf_code(code, input_bundle=input_bundle)


@pytest.mark.parametrize(
    ("lib", "statement"),
    [
        (
            """
event E:
    x: Bytes[INF]
    """,
            "log lib.E(x=b'abc')",
        ),
        (
            """
error E:
    x: Bytes[INF]
    """,
            "raise lib.E(b'abc')",
        ),
    ],
)
def test_imported_inf_event_and_error(compile_inf_code, make_input_bundle, lib, statement):
    code = f"""
import lib

@external
def foo():
    {statement}
    """
    input_bundle = make_input_bundle({"lib.vy": lib})
    compile_inf_code(code, input_bundle=input_bundle)


def test_inf_default_arg_expression_rejected():
    # default argument expressions may only be literals or environment
    # variables, so INF-typed expressions cannot appear in defaults with
    # a bounded arg type; INF-typed args are covered by the argument checks
    code = """
@external
def foo(x: uint256 = len(empty(Bytes[INF]))) -> uint256:
    return x
    """
    with pytest.raises(StateAccessViolation) as e:
        compiler.compile_code(code)
    assert e.value.message == "Value must be literal or environment variable"


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


def test_inf_pure_param(compile_inf_code):
    code = """
@pure
@external
def foo(x: Bytes[INF]) -> Bytes[INF]:
    return x
    """
    compile_inf_code(code)


def test_inf_pure_param_string(compile_inf_code):
    code = """
@pure
@external
def foo(x: String[INF]) -> String[INF]:
    return x
    """
    compile_inf_code(code)


def test_inf_pure_return(compile_inf_code):
    code = """
@pure
@external
def foo() -> Bytes[INF]:
    return b""
    """
    compile_inf_code(code)


def test_inf_pure_local_var(compile_inf_code):
    code = """
@pure
@external
def foo() -> Bytes[INF]:
    x: Bytes[INF] = b""
    return x
    """
    compile_inf_code(code)


def test_inf_pure_internal(compile_inf_code):
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
    compile_inf_code(code)


def test_wildcard_return_dynamic_element_requires_expected_bound():
    rejected = """
interface I:
    def foo() -> DynArray[Bytes[10], ...]: view

@external
def f(a: address) -> uint256:
    return len(staticcall I(a).foo())
    """
    with pytest.raises(StructureException) as e:
        compiler.compile_code(rejected)
    assert e.value.message == "DynArray[..., INF] is only supported with ABI-static element types"

    accepted = """
interface I:
    def foo() -> DynArray[Bytes[10], ...]: view

@external
def f(a: address) -> DynArray[Bytes[10], 5]:
    return staticcall I(a).foo()
    """
    compiler.compile_code(accepted)


def test_wildcard_arg_dynamic_element_requires_expected_bound():
    rejected = """
interface I:
    def foo(xs: DynArray[Bytes[10], ...]): nonpayable

@external
def f(a: address):
    extcall I(a).foo([])
    """
    with pytest.raises(StructureException) as e:
        compiler.compile_code(rejected)
    assert e.value.message == "DynArray[..., INF] is only supported with ABI-static element types"

    accepted = """
interface I:
    def foo(xs: DynArray[Bytes[10], ...]): nonpayable

@external
def f(a: address, xs: DynArray[Bytes[10], 5]):
    extcall I(a).foo(xs)
    """
    compiler.compile_code(accepted)


@pytest.mark.parametrize("element_type", ["Bytes[...]", "DynArray[uint256, ...]"])
def test_wildcard_arg_rejects_resolved_unbounded_element(element_type):
    code = f"""
interface I:
    def foo(xs: DynArray[{element_type}, 5]): nonpayable

@external
def f(a: address):
    extcall I(a).foo([])
    """
    with pytest.raises(StructureException) as e:
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))
    assert e.value.message == "DynArray element types cannot contain unbounded sequence types"


@pytest.mark.parametrize("arg_source", ["xs", "[]", "[1, 2]"])
def test_wildcard_arg_accepts_bounded_values(arg_source):
    # bounded variables and literals passed to a wildcard interface arg compile
    code = f"""
interface I:
    def foo(xs: DynArray[uint256, ...]): nonpayable

@external
def f(a: address):
    xs: DynArray[uint256, 3] = [1, 2, 3]
    extcall I(a).foo({arg_source})
    """
    compiler.compile_code(code)


def test_wildcard_tuple_interface_arg_rejects_inf_source():
    code = """
interface I:
    def foo(x: (Bytes[...], uint256)) -> uint256: view

@external
def f(a: address, x: Bytes[INF]) -> uint256:
    return staticcall I(a).foo((x, 1))
    """
    with pytest.raises(StructureException) as e:
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))
    message = "Function arguments cannot contain unbounded sequence types inside aggregate types"
    assert e.value.message == message


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
    with pytest.raises(StructureException) as e:
        compiler.compile_code(code, settings=Settings(experimental_codegen=True))
    assert e.value.message == "DynArray[..., INF] is only supported with ABI-static element types"


def test_imported_wildcard_event_accepts_inf_arg(make_input_bundle):
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
    compiler.compile_code(
        code,
        output_formats=["bytecode"],
        input_bundle=input_bundle,
        settings=Settings(experimental_codegen=True),
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
    compiler.compile_code(code, output_formats=["bytecode"], input_bundle=input_bundle)


def test_bounded_event_accepts_wildcard_call_return():
    code = """
event Foo:
    x: Bytes[10]

interface I:
    def foo() -> Bytes[...]: view

@external
def emit(a: address):
    log Foo(x=staticcall I(a).foo())
    """
    compiler.compile_code(code, output_formats=["bytecode"])


@pytest.mark.parametrize(
    ("abi_item", "statement"),
    [
        (
            {
                "anonymous": False,
                "inputs": [{"indexed": False, "name": "x", "type": "bytes"}],
                "name": "Foo",
                "type": "event",
            },
            "log JSONInterface.Foo(x=staticcall JSONInterface(a).returns_bytes())",
        ),
        (
            {"inputs": [{"name": "x", "type": "bytes"}], "name": "Oops", "type": "error"},
            "raise JSONInterface.Oops(staticcall JSONInterface(a).returns_bytes())",
        ),
    ],
)
def test_imported_wildcard_user_type_accepts_wildcard_call_return(
    make_input_bundle, abi_item, statement
):
    # both wildcards resolve to INF, which events and errors can encode
    function_abi = {
        "inputs": [],
        "name": "returns_bytes",
        "outputs": [{"name": "", "type": "bytes"}],
        "stateMutability": "view",
        "type": "function",
    }
    code = f"""
import JSONInterface

@external
def run(a: address):
    {statement}
    """
    input_bundle = make_input_bundle({"JSONInterface.json": json.dumps([function_abi, abi_item])})
    compiler.compile_code(
        code,
        output_formats=["bytecode"],
        input_bundle=input_bundle,
        settings=Settings(experimental_codegen=True),
    )


def test_abi_encode_resolves_json_abi_wildcard_call_return(make_input_bundle):
    abi = [
        {
            "inputs": [],
            "name": "returns_bytes",
            "outputs": [{"name": "", "type": "bytes"}],
            "stateMutability": "view",
            "type": "function",
        }
    ]
    code = """
import JSONInterface

@external
def encode(a: JSONInterface) -> Bytes[INF]:
    return abi_encode(staticcall a.returns_bytes())
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


def test_imported_wildcard_error_accepts_inf_arg(make_input_bundle):
    abi = [{"inputs": [{"name": "x", "type": "bytes"}], "name": "Oops", "type": "error"}]
    code = """
import JSONInterface

@external
def boom(x: Bytes[INF]):
    raise JSONInterface.Oops(x)
    """
    input_bundle = make_input_bundle({"JSONInterface.json": json.dumps(abi)})
    compiler.compile_code(
        code,
        output_formats=["bytecode"],
        input_bundle=input_bundle,
        settings=Settings(experimental_codegen=True),
    )


def test_dynarray_inf_pure(compile_inf_code):
    code = """
@pure
@external
def foo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """
    compile_inf_code(code)


@pytest.mark.parametrize("output_format", ["ir_dict", "ir_runtime_dict"])
def test_legacy_ir_outputs_reject_inf_under_experimental_codegen(output_format):
    # these outputs are built from legacy IR even with experimental codegen
    # on. legacy codegen cannot compile unbounded sequence types, so the
    # request must fail with a user-facing error, not an internal one.
    code = """
@external
def foo(x: Bytes[INF]) -> Bytes[INF]:
    return x
    """
    settings = Settings(experimental_codegen=True)
    with pytest.raises(StructureException) as e:
        compiler.compile_code(code, output_formats=[output_format], settings=settings)
    assert e.value.message == "legacy IR output does not support unbounded sequence types"

    # bounded contracts still get legacy IR from these outputs
    bounded = """
@external
def foo(x: Bytes[10]) -> Bytes[10]:
    return x
    """
    out = compiler.compile_code(bounded, output_formats=[output_format], settings=settings)
    assert isinstance(out[output_format], dict)
