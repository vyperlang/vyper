import pytest

from vyper.compiler import compile_code
from vyper.exceptions import (
    ArgumentException,
    CallViolation,
    FunctionDeclarationException,
    VyperException,
)


def _run_bad_signature_override(
    make_input_bundle,
    params_override,
    return_type_override,
    return_expression_override,
    params_abstract,
    return_type_abstract,
    exc_type,
    message,
):
    def with_arrow(return_type: str | None) -> str:
        return f"-> {return_type}" if return_type is not None else ""

    contract = f"""
import foo

initializes: foo

@override(foo)
def bar({params_override}){with_arrow(return_type_override)}:
    return {return_expression_override}
    """

    foo = f"""
@abstract
def bar({params_abstract}){with_arrow(return_type_abstract)}: ...
    """

    input_bundle = make_input_bundle({"foo.vy": foo})

    with pytest.raises(exc_type) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert message in e.value.message


def test_correct_param_count(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        "",
        "uint256",
        "0",
        "x: uint256",
        "uint256",
        FunctionDeclarationException,
        "bar has 0 params, but it should have at least 1",
    )


def test_too_many_mandatory_params(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256, y: uint256",
        "uint256",
        "x + y",
        "x: uint256",
        "uint256",
        FunctionDeclarationException,
        "bar has mandatory parameter `y: uint256` not present in the method it overrides",
    )


# === PARAMETER MISMATCH ERRORS ===


def test_parameter_name_mismatch(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256",
        "uint256",
        "x",
        "y: uint256",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


def test_invalid_params_swapped(make_input_bundle):
    # Parameters swapped (same names and types but wrong positions)
    # Uses VyperException because both parameters mismatch, resulting in multiple errors
    _run_bad_signature_override(
        make_input_bundle,
        "y: uint256, x: uint256",
        "uint256",
        "x + y",
        "x: uint256, y: uint256",
        "uint256",
        VyperException,
        "Override parameter mismatch",
    )


def test_param_type_mismatch(make_input_bundle):
    # Parameter type mismatch with different types
    _run_bad_signature_override(
        make_input_bundle,
        "x: int256",
        "uint256",
        "convert(x, uint256)",
        "x: uint256",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


def test_second_param_type_mismatch(make_input_bundle):
    # Second parameter type mismatch
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256, y: uint256",
        "uint256",
        "x + y",
        "x: uint256, y: int256",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


def test_first_param_type_mismatch(make_input_bundle):
    # First parameter type mismatch with multiple parameters
    _run_bad_signature_override(
        make_input_bundle,
        "a: uint256, b: address, c: bool",
        "bool",
        "c",
        "a: int256, b: address, c: bool",
        "bool",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


def test_param_mismatch_array_size(make_input_bundle):
    # Fixed array parameter size mismatch
    _run_bad_signature_override(
        make_input_bundle,
        "arr: uint256[10]",
        "uint256",
        "arr[0]",
        "arr: uint256[5]",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


# === RETURN TYPE ERRORS ===


def test_override_return_mismatch1(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        # Has return type when abstract has none
        "x: uint256",
        "uint256",
        "x",
        "x: uint256",
        None,
        FunctionDeclarationException,
        "bar returns uint256 but the method it overrides does not return anything",
    )


def test_override_return_mismatch2(make_input_bundle):
    # No return type when abstract has one
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256",
        None,
        "",
        "x: uint256",
        "uint256",
        FunctionDeclarationException,
        "bar does not return anything but the method it overrides returns uint256",
    )


def test_override_return_mismatch3(make_input_bundle):
    # Different return types
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256",
        "int256",
        "convert(x, int256)",
        "x: uint256",
        "uint256",
        FunctionDeclarationException,
        "bar returns int256 but the method it overrides returns uint256",
    )


def test_override_return_mismatch4(make_input_bundle):
    # Return type mismatch with bool and uint256
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256, y: uint256, z: address",
        "bool",
        "True",
        "x: uint256, y: uint256, z: address",
        "uint256",
        FunctionDeclarationException,
        "bar returns bool but the method it overrides returns uint256",
    )


# === INVALID SUBTYPING - PARAMETERS ===


def test_string_param_invalid_subtype(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        "s: String[50]",
        "uint256",
        "len(s)",
        "s: String[100]",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


def test_dynarray_param_invalid_subtype(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        "arr: DynArray[uint256, 10]",
        "uint256",
        "len(arr)",
        "arr: DynArray[uint256, 20]",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


def test_bytes_param_invalid_subtype(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        "data: Bytes[32]",
        "uint256",
        "len(data)",
        "data: Bytes[64]",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


def test_middle_param_invalid_subtype(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        "a: address, s: String[50], c: bool",
        "bool",
        "c",
        "a: address, s: String[100], c: bool",
        "bool",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


# === INVALID SUBTYPING - RETURN TYPES ===


def test_string_return_invalid_supertype(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256",
        "String[100]",
        '"hello"',
        "x: uint256",
        "String[50]",
        FunctionDeclarationException,
        "bar returns String[100] but the method it overrides returns String[50]",
    )


def test_dynarray_return_invalid_supertype(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256",
        "DynArray[uint256, 20]",
        "[x, x]",
        "x: uint256",
        "DynArray[uint256, 10]",
        FunctionDeclarationException,
        "bar returns DynArray[uint256, 20] but the method it overrides returns"
        " DynArray[uint256, 10]",
    )


def test_bytes_return_invalid_supertype(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256",
        "Bytes[64]",
        'b""',
        "x: uint256",
        "Bytes[32]",
        FunctionDeclarationException,
        "bar returns Bytes[64] but the method it overrides returns Bytes[32]",
    )


# === ABSTRACT METHODS WITH OPTIONAL PARAMETERS ===


def test_mismatch_default_param_value(make_input_bundle):
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256, y: uint256 = 20",
        "uint256",
        "x + y",
        "x: uint256, y: uint256 = 10",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


def test_invalid_mandatory_override(make_input_bundle):
    # Optional parameter in abstract cannot be mandatory in override
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256, y: uint256",
        "uint256",
        "x + y",
        "x: uint256, y: uint256 = ...",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


# === DIFFERENT DEFAULT VALUES ===


def test_different_default_values_env1(make_input_bundle):
    # Different environment variables (msg.sender vs tx.origin)
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256, a: address = tx.origin",
        "address",
        "a",
        "x: uint256, a: address = msg.sender",
        "address",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


def test_different_default_values_env2(make_input_bundle):
    # Different environment variables (block.number vs block.timestamp)
    _run_bad_signature_override(
        make_input_bundle,
        "x: uint256, b: uint256 = block.timestamp",
        "uint256",
        "b",
        "x: uint256, b: uint256 = block.number",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    )


# === VALID DECORATOR OVERRIDES ===


VALID_DECORATOR_OVERRIDES = [
    # abstract_decorators, override_decorators
    # Mutability only - same mutability
    ("@payable", "@payable"),
    ("@nonpayable", "@nonpayable"),
    ("@view", "@view"),
    ("@pure", "@pure"),
    ("", ""),
    # Mutability only - stricter mutability (valid)
    ("@payable", "@nonpayable"),
    ("@payable", ""),
    ("@payable", "@view"),
    ("@payable", "@pure"),
    ("@nonpayable", "@view"),
    ("@nonpayable", "@pure"),
    ("", "@view"),
    ("", "@pure"),
    ("@view", "@pure"),
    # Nonreentrant only - matching
    ("@nonreentrant", "@nonreentrant"),
    # Nonreentrant + mutability combinations (valid)
    ("@nonreentrant\n@nonpayable", "@nonreentrant\n@nonpayable"),
    ("@nonreentrant\n@view", "@nonreentrant\n@view"),
    ("@nonreentrant\n@payable", "@nonreentrant\n@nonpayable"),
    ("@nonreentrant\n@payable", "@nonreentrant"),
    ("@nonreentrant", "@nonreentrant\n@view"),
    ("@nonreentrant\n@nonpayable", "@nonreentrant\n@view"),
    ("@nonreentrant\n@payable", "@nonreentrant\n@view"),
]


@pytest.mark.parametrize("abstract_decorators,override_decorators", VALID_DECORATOR_OVERRIDES)
def test_decorator_override_valid(make_input_bundle, abstract_decorators, override_decorators):
    """Test valid decorator overrides (including mutability and nonreentrant)"""

    contract = f"""
import foo

initializes: foo

@override(foo)
{override_decorators}
def bar() -> uint256:
    return 42
    """

    foo = f"""
@abstract
{abstract_decorators}
def bar() -> uint256: ...
    """

    input_bundle = make_input_bundle({"foo.vy": foo})
    # Should compile without errors
    compile_code(contract, input_bundle=input_bundle)


def _run_failing_decorator_override(
    make_input_bundle, abstract_decorators, override_decorators, message, hint=None
):
    contract = f"""
import foo

initializes: foo

@override(foo)
{override_decorators}
def bar() -> uint256:
    return 42
    """

    foo = f"""
@abstract
{abstract_decorators}
def bar() -> uint256: ...
    """

    input_bundle = make_input_bundle({"foo.vy": foo})
    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert message in e.value.message
    if hint is not None:
        assert e.value.hint == hint


# === INVALID MUTABILITY - LESS STRICT ===


def test_mutability_nonpayable_to_payable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@nonpayable",
        "@payable",
        "bar is payable but it overrides a nonpayable method",
        hint="change bar to be nonpayable (or stricter)",
    )


def test_mutability_default_to_payable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "",
        "@payable",
        "bar is payable but it overrides a nonpayable method",
        hint="change bar to be nonpayable (or stricter)",
    )


def test_mutability_view_to_nonpayable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@view",
        "@nonpayable",
        "bar is nonpayable but it overrides a view method",
        hint="change bar to be view (or stricter)",
    )


def test_mutability_view_to_default(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@view",
        "",
        "bar is nonpayable but it overrides a view method",
        hint="change bar to be view (or stricter)",
    )


def test_mutability_view_to_payable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@view",
        "@payable",
        "bar is payable but it overrides a view method",
        hint="change bar to be view (or stricter)",
    )


def test_mutability_pure_to_view(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@pure",
        "@view",
        "bar is view but it overrides a pure method",
        hint="change bar to be pure",
    )


def test_mutability_pure_to_nonpayable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@pure",
        "@nonpayable",
        "bar is nonpayable but it overrides a pure method",
        hint="change bar to be pure",
    )


def test_mutability_pure_to_default(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@pure",
        "",
        "bar is nonpayable but it overrides a pure method",
        hint="change bar to be pure",
    )


def test_mutability_pure_to_payable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@pure",
        "@payable",
        "bar is payable but it overrides a pure method",
        hint="change bar to be pure",
    )


# === INVALID REENTRANCY MISMATCH ===


def test_nonreentrant_to_default(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@nonreentrant",
        "",
        "bar is reentrant but it overrides a non-reentrant method",
    )


def test_nonreentrant_to_nonpayable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@nonreentrant",
        "@nonpayable",
        "bar is reentrant but it overrides a non-reentrant method",
    )


def test_default_to_nonreentrant(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "",
        "@nonreentrant",
        "bar is non-reentrant but it overrides a reentrant method",
    )


def test_nonpayable_to_nonreentrant_nonpayable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@nonpayable",
        "@nonreentrant\n@nonpayable",
        "bar is non-reentrant but it overrides a reentrant method",
    )


# === COMBINED - NONREENTRANT MISSING ===


def test_nonreentrant_nonpayable_to_nonpayable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@nonreentrant\n@nonpayable",
        "@nonpayable",
        "bar is reentrant but it overrides a non-reentrant method",
    )


def test_nonreentrant_view_to_view(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@nonreentrant\n@view",
        "@view",
        "bar is reentrant but it overrides a non-reentrant method",
    )


def test_nonreentrant_payable_to_payable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@nonreentrant\n@payable",
        "@payable",
        "bar is reentrant but it overrides a non-reentrant method",
    )


# === COMBINED - NONREENTRANT ADDED ===


def test_view_to_nonreentrant_view(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@view",
        "@nonreentrant\n@view",
        "bar is non-reentrant but it overrides a reentrant method",
    )


def test_payable_to_nonreentrant_payable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@payable",
        "@nonreentrant\n@payable",
        "bar is non-reentrant but it overrides a reentrant method",
    )


# === COMBINED - MUTABILITY LESS STRICT WITH NONREENTRANT ===


def test_nonreentrant_to_nonreentrant_payable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@nonreentrant",
        "@nonreentrant\n@payable",
        "bar is payable but it overrides a nonpayable method",
        hint="change bar to be nonpayable (or stricter)",
    )


def test_nonreentrant_nonpayable_to_nonreentrant_payable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@nonreentrant\n@nonpayable",
        "@nonreentrant\n@payable",
        "bar is payable but it overrides a nonpayable method",
        hint="change bar to be nonpayable (or stricter)",
    )


def test_nonreentrant_view_to_nonreentrant_nonpayable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@nonreentrant\n@view",
        "@nonreentrant\n@nonpayable",
        "bar is nonpayable but it overrides a view method",
        hint="change bar to be view (or stricter)",
    )


def test_nonreentrant_view_to_nonreentrant_payable(make_input_bundle):
    _run_failing_decorator_override(
        make_input_bundle,
        "@nonreentrant\n@view",
        "@nonreentrant\n@payable",
        "bar is payable but it overrides a view method",
        hint="change bar to be view (or stricter)",
    )


# === OVERRIDE STRUCTURAL ERRORS ===


def test_override_non_abstract_method_fails(make_input_bundle):
    """Test that overriding a non-abstract method fails with proper error"""
    contract = """
import foo

initializes: foo

@override(foo)
def bar() -> uint256:
    return 42
    """

    foo = """
def bar() -> uint256:
    return 100
    """

    input_bundle = make_input_bundle({"foo.vy": foo})

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert e.value.message == "Cannot override `foo.bar`, it is not an abstract method!"


def test_override_nonexistent_method_fails(make_input_bundle):
    """Test that overriding a method that doesn't exist in the module fails"""
    contract = """
import foo

initializes: foo

@override(foo)
def bar() -> uint256:
    return 42
    """

    foo = """
@abstract
def different_method() -> uint256: ...
    """

    input_bundle = make_input_bundle({"foo.vy": foo})

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert e.value.message == "Tried to override `foo.bar`, but it does not exist"


def test_override_nonexistent_method_with_hint(make_input_bundle):
    """Test that overriding a nonexistent method suggests similar names"""
    contract = """
import foo

initializes: foo

@override(foo)
def long_method_name_z() -> uint256:
    return 42
    """

    foo = """
@abstract
def long_method_name_a() -> uint256: ...
    """

    input_bundle = make_input_bundle({"foo.vy": foo})

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert e.value.message == "Tried to override `foo.long_method_name_z`, but it does not exist"
    assert e.value.hint == "Did you mean 'long_method_name_a'?"


def test_duplicate_override_fails(make_input_bundle, tmp_path):
    """Test that overriding the same abstract method twice fails with proper error"""
    contract = """
import foo
import bar_override
import baz_override

initializes: foo
initializes: bar_override
initializes: baz_override
    """

    foo = """
@abstract
def some_method() -> uint256: ...
    """

    bar_override = """
import foo
initializes: foo

@override(foo)
def some_method() -> uint256:
    return 100
    """

    baz_override = """
import foo
initializes: foo

@override(foo)  # This should fail - method already overridden by bar_override
def some_method() -> uint256:
    return 200
    """

    input_bundle = make_input_bundle(
        {"foo.vy": foo, "bar_override.vy": bar_override, "baz_override.vy": baz_override}
    )

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract, input_bundle=input_bundle)

    bar_path = (tmp_path / "bar_override.vy").as_posix()
    baz_path = (tmp_path / "baz_override.vy").as_posix()

    assert (
        e.value.message
        == f"`foo.some_method` was already overridden in `{bar_path}`!"
    )
    expected_hint = "the likely root cause is that `foo` has been initialized"
    expected_hint += f" in both `{baz_path}` and"
    expected_hint += f" `{bar_path}`, which is an error"
    assert e.value.hint == expected_hint


def test_override_validation_order(make_input_bundle):
    """Test that validation errors are reported in the correct order"""

    # Test 1: Non-initialized module error should come first
    contract1 = """
import foo
# Missing initializes

@override(foo)
def bar() -> uint256:
    return 42
    """

    foo1 = """
def bar() -> uint256:  # Not abstract, but we should get non-initialized error first
    return 100
    """

    input_bundle1 = make_input_bundle({"foo.vy": foo1})

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract1, input_bundle=input_bundle1)

    # Should fail on non-initialized module before checking if method is abstract
    assert e.value.message == "Cannot override `foo.bar` as it is not initialized"

    # Test 2: Non-abstract method error should come after initialization check passes
    contract2 = """
import foo

initializes: foo

@override(foo)
def bar() -> uint256:
    return 42
    """

    foo2 = """
def bar() -> uint256:  # Not abstract
    return 100
    """

    input_bundle2 = make_input_bundle({"foo.vy": foo2})

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract2, input_bundle=input_bundle2)

    # Should fail on non-abstract method
    assert e.value.message == "Cannot override `foo.bar`, it is not an abstract method!"


def test_override_with_default_param_changes_signature(make_input_bundle):
    """
    Test that we can't call a.foo(1) if in 'a' it's foo() but overridden by foo(x: uint256 = 0)
    """

    abstract_module = """
@abstract
def foo() -> uint256: ...
    """

    override_module = """
import abstract_module

initializes: abstract_module

@override(abstract_module)
def foo(x: uint256 = 0) -> uint256:
    return x + 42
    """

    contract = """
import abstract_module
import override_module

uses: abstract_module
initializes: override_module

@external
def test_foo() -> uint256:
    return abstract_module.foo(1) # Not valid for the abstract we are calling !
    """

    input_bundle = make_input_bundle(
        {"abstract_module.vy": abstract_module, "override_module.vy": override_module}
    )

    with pytest.raises(ArgumentException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert "Invalid argument count for call to 'foo': expected 0, got 1" in str(e.value)


def test_override_optional_param_still_mandatory_via_abstract(make_input_bundle):
    """Test that we can't omit a mandatory param when calling through abstract,
    even if the override makes it optional."""

    abstract_module = """
@abstract
def foo(x: uint256, y: uint256) -> uint256: ...
    """

    override_module = """
import abstract_module

initializes: abstract_module

@override(abstract_module)
def foo(x: uint256, y: uint256 = 10) -> uint256:
    return x + y
    """

    contract = """
import abstract_module
import override_module

uses: abstract_module
initializes: override_module

@external
def test_foo() -> uint256:
    return abstract_module.foo(5)  # Missing y - not valid for the abstract!
    """

    input_bundle = make_input_bundle(
        {"abstract_module.vy": abstract_module, "override_module.vy": override_module}
    )

    with pytest.raises(ArgumentException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert "Invalid argument count for call to 'foo': expected 2, got 1" in str(e.value)


def test_override_recursion_fails(make_input_bundle):
    abstract_m = """

def forwarder() -> uint256:
    return self.foo()

@abstract
def foo() -> uint256: ...
    """

    contract = """
import abstract_m

initializes: abstract_m

@override(abstract_m)
def foo() -> uint256:
    return abstract_m.forwarder()
    """

    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m})

    with pytest.raises(CallViolation) as e:
        compile_code(contract, input_bundle=input_bundle)

    # TODO: Maybe improve error message so it includes overrides ?
    # Something like a.foo -> b.forwarder -> b.foo -resolves_to-> a.foo
    # Note: The cycle can be detected starting from either function depending on processing order
    assert (
        "Contract contains cyclic function call: forwarder -> foo -> forwarder" == e.value.message
    )


def test_must_override_all_abstract_methods(make_input_bundle):
    """Test that initializing an abstract module requires overriding ALL its abstract methods"""

    abstract_module = """
@abstract
def foo() -> uint256: ...

@abstract
def bar() -> uint256: ...
    """

    contract = """
import abstract_module

initializes: abstract_module

@override(abstract_module)
def foo() -> uint256:
    return 42

# Missing override for bar!
    """

    input_bundle = make_input_bundle({"abstract_module.vy": abstract_module})

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert "Abstract function was not overridden" == e.value.message
    assert "bar" in e.value.annotations[0].node_source_code


def test_contract_cannot_have_abstract_methods():
    """Test that a top-level contract cannot have abstract methods"""

    contract = """
@abstract
def foo() -> uint256: ...

@external
def bar() -> uint256:
    return self.foo()
    """

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract)

    assert "Abstract function was not overridden" == e.value.message
    assert "foo" in e.value.annotations[0].node_source_code


def test_cannot_call_overridden_method(make_input_bundle):
    """Test that you cannot call a method that you override"""

    abstract_module = """
@abstract
def foo() -> uint256: ...
    """

    contract = """
import abstract_module

initializes: abstract_module

@override(abstract_module)
def foo() -> uint256:
    return abstract_module.foo()  # Should fail - can't call method we override
    """

    input_bundle = make_input_bundle({"abstract_module.vy": abstract_module})

    with pytest.raises(CallViolation) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert "foo" in e.value.message


def test_abstract_method_body_must_be_ellipsis(make_input_bundle):
    """Test that abstract method body must be ... only (no actual code)"""

    abstract_module = """
@abstract
def foo() -> uint256:
    return 42  # Should fail - body must be ...
    """

    contract = """
import abstract_module

initializes: abstract_module

@override(abstract_module)
def foo() -> uint256:
    return 100
    """

    input_bundle = make_input_bundle({"abstract_module.vy": abstract_module})

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert "abstract" in e.value.message.lower()


def test_ellipsis_cannot_override_concrete_default_parameter(make_input_bundle):
    """Test that ellipsis cannot override a concrete default parameter value"""

    module_c = """
@abstract
def foo(x: uint256 = 10) -> uint256: ...
    """

    module_b = """
import module_c

initializes: module_c

@abstract
@override(module_c) # v Ellipsis overrides `10` from module_c
def foo(x: uint256 = ...) -> uint256: ...
    """

    module_a = """
import module_b

initializes: module_b

@override(module_b)
def foo(x: uint256 = 10) -> uint256:
    return x
    """

    contract = """
import module_a
import module_c

initializes: module_a
uses: module_c

@external
def test() -> uint256:
    return module_c.foo()
    """

    input_bundle = make_input_bundle(
        {"module_c.vy": module_c, "module_b.vy": module_b, "module_a.vy": module_a}
    )

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert "Override parameter mismatch" in e.value.message


def test_different_import_same_name_default_mismatch(make_input_bundle):
    """
    Test that lib.BAR in abstract != lib.BAR in override when lib is a different import.
    Even though syntactically identical (both `lib.BAR`), they refer to different modules.
    The comparison resolves module identity, not just the alias name.
    """
    # Two different libraries with same constant name
    lib_a = """
BAR: constant(uint256) = 10
    """

    lib_b = """
BAR: constant(uint256) = 10
    """

    # Abstract module imports lib_a as 'lib'
    abstract_module = """
import lib_a as lib

@abstract
def foo(x: uint256 = lib.BAR) -> uint256: ...
    """

    # Override imports lib_b as 'lib' - same alias name, different module!
    override_contract = """
import lib_b as lib
import abstract_module

initializes: abstract_module

@override(abstract_module)
def foo(x: uint256 = lib.BAR) -> uint256:
    return x
    """

    main_contract = """
import override_contract
import abstract_module

initializes: override_contract
uses: abstract_module

@external
def test() -> uint256:
    return abstract_module.foo()
    """

    input_bundle = make_input_bundle(
        {
            "lib_a.vy": lib_a,
            "lib_b.vy": lib_b,
            "abstract_module.vy": abstract_module,
            "override_contract.vy": override_contract,
        }
    )

    # Should fail: both defaults are `lib.BAR` but `lib` refers to different modules
    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(main_contract, input_bundle=input_bundle)

    assert "Override parameter mismatch" in e.value.message


def test_immutable_not_equal_across_modules(make_input_bundle):
    """
    Test that self.FOO (immutable) in two different modules is NOT semantically equal,
    even if they have the same name. Each module's immutable is distinct.
    """
    abstract_module = """
FOO: immutable(uint256)

@deploy
def __init__():
    FOO = 42

@abstract
def bar(x: uint256 = FOO) -> uint256: ...
    """

    # Override module has its own FOO immutable - should NOT match
    override_contract = """
import abstract_module

initializes: abstract_module

FOO: immutable(uint256)

@deploy
def __init__():
    FOO = 100
    abstract_module.__init__()

@override(abstract_module)
def bar(x: uint256 = FOO) -> uint256:
    return x
    """

    input_bundle = make_input_bundle({"abstract_module.vy": abstract_module})

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(override_contract, input_bundle=input_bundle)

    assert "Override parameter mismatch" in e.value.message
