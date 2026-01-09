import pytest

from vyper.exceptions import FunctionDeclarationException, InitializerException


def test_basic_default_default_param_function(get_contract, make_input_bundle):
    # Both modules "call" at least one method from the other one
    contract = """
import abstract_m

initializes: abstract_m

@external
def my_method() -> uint256:
    return abstract_m.foo()

@override(abstract_m)
def bar() -> uint256:
    return abstract_m.const()
    """

    abstract_m = """
def foo() -> uint256:
    return self.bar()

@abstract
def bar() -> uint256: ...

def const() -> uint256:
    return 101
    """
    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m})
    c = get_contract(contract, input_bundle=input_bundle)

    assert c.my_method() == 101


def test_stateful_override_without_initializes(get_contract, make_input_bundle):
    contract = """
import abstract_m
import override_m

# initializes: override_m # should fail gracefully without this

@external
def my_method() -> uint256:
    return abstract_m.bar()
    """

    abstract_m = """
@abstract
def bar() -> uint256: ...
    """

    override_m = """
import abstract_m
initializes: abstract_m

counter: uint256

@override(abstract_m)
def bar() -> uint256:
    self.counter += 1
    return 101
    """
    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m, "override_m.vy": override_m})

    with pytest.raises(InitializerException) as e:
        get_contract(contract, input_bundle=input_bundle)

    # Verify the error message is helpful
    expected_msg = "Cannot call `bar` from `abstract_m` - it is overridden in `override_m` which"
    " accesses state, but `override_m` is not initialized"
    assert expected_msg == e.value.message
    assert "add `initializes: override_m` as a top-level statement to your contract" == e.value.hint


def test_stateful_override_with_initializes(get_contract, make_input_bundle):
    # Test that the same contract works when override_m is properly initialized
    contract = """
import abstract_m
import override_m

initializes: override_m  # Now properly initialized

@external
def my_method() -> uint256:
    return abstract_m.bar()
    """

    abstract_m = """
@abstract
def bar() -> uint256: ...
    """

    override_m = """
import abstract_m
initializes: abstract_m

counter: uint256

@override(abstract_m)
def bar() -> uint256:
    self.counter += 1
    return 101
    """
    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m, "override_m.vy": override_m})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.my_method() == 101


SUCCESSFUL_OVERRIDES = [
    # params, ret_t, ret_v,
    # params, ret_t,
    # input, expected_output
    # === SUCCESSFUL BASIC OVERRIDES ===
    # Basic successful override
    ("x: uint256", "uint256", "x", "x: uint256", "uint256", "42", 42),
    # Boolean parameter and return type matching
    ("flag: bool", "bool", "flag", "flag: bool", "bool", "True", True),
    # Bytes32 parameter matching
    (
        "data: bytes32",
        "bytes32",
        "data",
        "data: bytes32",
        "bytes32",
        "0x" + "42" * 32,
        bytes.fromhex("42" * 32),
    ),
    # Address parameter matching
    (
        "addr: address",
        "address",
        "addr",
        "addr: address",
        "address",
        "msg.sender",
        None,  # Will be replaced with actual sender
    ),
    # DynArray parameter matching exactly
    (
        "arr: DynArray[uint256, 10]",
        "uint256",
        "len(arr)",
        "arr: DynArray[uint256, 10]",
        "uint256",
        "[1, 2, 3]",
        3,
    ),
    # Multiple parameters all matching
    ("x: uint256, y: int256", "uint256", "x", "x: uint256, y: int256", "uint256", "100, -50", 100),
    # Complex parameter combination all matching
    (
        "a: address, b: uint256, c: bool, d: bytes32",
        "address",
        "a",
        "a: address, b: uint256, c: bool, d: bytes32",
        "address",
        "msg.sender, 100, True, 0x" + "00" * 32,
        None,  # Will be replaced with actual sender
    ),
    # === VALID SUBTYPING/SUPERTYPING ===
    # String parameter with valid supertype
    ("s: String[100]", "uint256", "len(s)", "s: String[50]", "uint256", '"hello"', 5),
    # String parameter with valid supertype (larger)
    ("s: String[200]", "uint256", "len(s)", "s: String[100]", "uint256", '"test string"', 11),
    # DynArray parameter with valid supertype
    (
        "arr: DynArray[uint256, 20]",
        "uint256",
        "len(arr)",
        "arr: DynArray[uint256, 10]",
        "uint256",
        "[1, 2, 3, 4, 5]",
        5,
    ),
    # Bytes parameter with valid supertype
    (
        "data: Bytes[64]",
        "uint256",
        "len(data)",
        "data: Bytes[32]",
        "uint256",
        'b"\\x01\\x02\\x03\\x04"',
        4,
    ),
    # String return with valid subtype
    ("x: uint256", "String[50]", '"hello"', "x: uint256", "String[100]", "0", "hello"),
]

FAILING_OVERRIDES = [
    # params, ret_t, ret_v,
    # params, ret_t,
    # except, message
    # === PARAMETER COUNT ERRORS ===
    # Too few parameters
    (
        "",
        "uint256",
        "0",
        "x: uint256",
        "uint256",
        FunctionDeclarationException,
        "Override does not have the correct number of parameters.",
    ),
    # Too many parameters
    (
        "x: uint256, y: uint256",
        "uint256",
        "x + y",
        "x: uint256",
        "uint256",
        FunctionDeclarationException,
        "Override does not have the correct number of parameters.",
    ),
    # === PARAMETER MISMATCH ERRORS ===
    # Parameter name mismatch
    (
        "x: uint256",
        "uint256",
        "x",
        "y: uint256",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # Parameter type mismatch with different types
    (
        "x: int256",
        "uint256",
        "convert(x, uint256)",
        "x: uint256",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # Second parameter type mismatch
    (
        "x: uint256, y: uint256",
        "uint256",
        "x + y",
        "x: uint256, y: int256",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # First parameter type mismatch in multiple parameters
    (
        "a: uint256, b: address, c: bool",
        "bool",
        "c",
        "a: int256, b: address, c: bool",
        "bool",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # Fixed array parameter size mismatch
    (
        "arr: uint256[10]",
        "uint256",
        "arr[0]",
        "arr: uint256[5]",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # === RETURN TYPE ERRORS ===
    # Has return type when abstract has none
    (
        "x: uint256",
        "uint256",
        "x",
        "x: uint256",
        None,
        FunctionDeclarationException,
        "Override return type mismatch",
    ),
    # No return type when abstract has one
    (
        "x: uint256",
        None,
        "",
        "x: uint256",
        "uint256",
        FunctionDeclarationException,
        "Override return type mismatch",
    ),
    # Different return types
    (
        "x: uint256",
        "int256",
        "convert(x, int256)",
        "x: uint256",
        "uint256",
        FunctionDeclarationException,
        "Override return type mismatch",
    ),
    # Return type mismatch with bool and uint256
    (
        "x: uint256, y: uint256, z: address",
        "bool",
        "True",
        "x: uint256, y: uint256, z: address",
        "uint256",
        FunctionDeclarationException,
        "Override return type mismatch",
    ),
    # === INVALID SUBTYPING - PARAMETERS ===
    # String parameter with invalid subtype
    (
        "s: String[50]",
        "uint256",
        "len(s)",
        "s: String[100]",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # DynArray parameter with invalid subtype
    (
        "arr: DynArray[uint256, 10]",
        "uint256",
        "len(arr)",
        "arr: DynArray[uint256, 20]",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # Bytes parameter with invalid subtype
    (
        "data: Bytes[32]",
        "uint256",
        "len(data)",
        "data: Bytes[64]",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # Middle parameter with invalid subtype
    (
        "a: address, s: String[50], c: bool",
        "bool",
        "c",
        "a: address, s: String[100], c: bool",
        "bool",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # === INVALID SUBTYPING - RETURN TYPES ===
    # String return with invalid supertype
    (
        "x: uint256",
        "String[100]",
        '"hello"',
        "x: uint256",
        "String[50]",
        FunctionDeclarationException,
        "Override return type mismatch",
    ),
    # DynArray return with invalid supertype
    (
        "x: uint256",
        "DynArray[uint256, 20]",
        "[x, x]",
        "x: uint256",
        "DynArray[uint256, 10]",
        FunctionDeclarationException,
        "Override return type mismatch",
    ),
    # Bytes return with invalid supertype
    (
        "x: uint256",
        "Bytes[64]",
        'b""',
        "x: uint256",
        "Bytes[32]",
        FunctionDeclarationException,
        "Override return type mismatch",
    ),
]


@pytest.mark.parametrize("successful_override", SUCCESSFUL_OVERRIDES)
def test_successful_signature_override(get_contract, make_input_bundle, successful_override):
    (
        params_override,
        return_type_override,
        return_expression_override,
        params_abstract,
        return_type_abstract,
        input,
        expected_output,
    ) = successful_override

    def with_arrow(return_type: str | None) -> str:
        return f"-> {return_type}" if return_type is not None else ""

    contract = f"""
import foo

initializes: foo

@external
def value(){with_arrow(return_type_abstract)}:
    return foo.forwarder({input})

@override(foo)
def bar({params_override}){with_arrow(return_type_override)}:
    return {return_expression_override}
    """

    # Extract parameter names for the forwarder call
    def extract_param_names(params: str) -> str:
        if not params:
            return ""
        param_list = []
        for param in params.split(","):
            param = param.strip()
            if ":" in param:
                name = param.split(":")[0].strip()
                param_list.append(name)
        return ", ".join(param_list)

    param_names = extract_param_names(params_abstract)

    foo = f"""
def forwarder({params_abstract}){with_arrow(return_type_abstract)}:
    return self.bar({param_names})

@abstract
def bar({params_abstract}){with_arrow(return_type_abstract)}: ...
    """

    input_bundle = make_input_bundle({"foo.vy": foo})

    # Should compile without errors
    c = get_contract(contract, input_bundle=input_bundle)

    # Handle special cases where expected_output depends on runtime values
    if expected_output is None:
        if return_type_override == "address":
            # For address returns, we expect msg.sender to be returned
            expected_output = c.value()  # Just verify it runs without error
            assert expected_output is not None
        else:
            # Just verify it runs without error
            c.value()
    else:
        assert c.value() == expected_output


@pytest.mark.parametrize("failing_override", FAILING_OVERRIDES)
def test_failing_signature_override(get_contract, make_input_bundle, failing_override):
    (
        params_override,
        return_type_override,
        return_expression_override,
        params_abstract,
        return_type_abstract,
        raised_exception,
        message,
    ) = failing_override

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

    with pytest.raises(raised_exception) as e:
        get_contract(contract, input_bundle=input_bundle)

    assert message in e.value.message


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
def test_decorator_override_valid(
    get_contract, make_input_bundle, abstract_decorators, override_decorators
):
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
    get_contract(contract, input_bundle=input_bundle)


INVALID_DECORATOR_OVERRIDES = [
    # abstract_decorators, override_decorators, expected_message, expected_hint
    # Mutability only - less strict (invalid)
    (
        "@nonpayable",
        "@payable",
        "Override mutability mismatch: Got payable, but expected nonpayable (or stricter)",
        None,
    ),
    (
        "",
        "@payable",
        "Override mutability mismatch: Got payable, but expected nonpayable (or stricter)",
        None,
    ),
    (
        "@view",
        "@nonpayable",
        "Override mutability mismatch: Got nonpayable, but expected view (or stricter)",
        None,
    ),
    (
        "@view",
        "",
        "Override mutability mismatch: Got nonpayable, but expected view (or stricter)",
        None,
    ),
    (
        "@view",
        "@payable",
        "Override mutability mismatch: Got payable, but expected view (or stricter)",
        None,
    ),
    ("@pure", "@view", "Override mutability mismatch: Got view, but expected pure", None),
    (
        "@pure",
        "@nonpayable",
        "Override mutability mismatch: Got nonpayable, but expected pure",
        None,
    ),
    ("@pure", "", "Override mutability mismatch: Got nonpayable, but expected pure", None),
    ("@pure", "@payable", "Override mutability mismatch: Got payable, but expected pure", None),
    # Nonreentrant mismatch
    (
        "@nonreentrant",
        "",
        "Override reentrancy mismatch: Override isn't non-reentrant, unlike the method it is"
        " overriding.",
        "add a @nonreentrant decorator",
    ),
    (
        "@nonreentrant",
        "@nonpayable",
        "Override reentrancy mismatch: Override isn't non-reentrant, unlike the method it is"
        " overriding.",
        "add a @nonreentrant decorator",
    ),
    (
        "",
        "@nonreentrant",
        "Override reentrancy mismatch: Override is non-reentrant, unlike the method it is"
        " overriding.",
        "remove the @nonreentrant decorator",
    ),
    (
        "@nonpayable",
        "@nonreentrant\n@nonpayable",
        "Override reentrancy mismatch: Override is non-reentrant, unlike the method it is"
        " overriding.",
        "remove the @nonreentrant decorator",
    ),
    # Combined decorator mismatches - nonreentrant missing
    (
        "@nonreentrant\n@nonpayable",
        "@nonpayable",
        "Override reentrancy mismatch: Override isn't non-reentrant, unlike the method it is"
        " overriding.",
        "add a @nonreentrant decorator",
    ),
    (
        "@nonreentrant\n@view",
        "@view",
        "Override reentrancy mismatch: Override isn't non-reentrant, unlike the method it is"
        " overriding.",
        "add a @nonreentrant decorator",
    ),
    (
        "@nonreentrant\n@payable",
        "@payable",
        "Override reentrancy mismatch: Override isn't non-reentrant, unlike the method it is"
        " overriding.",
        "add a @nonreentrant decorator",
    ),
    # Combined decorator mismatches - nonreentrant added
    (
        "@view",
        "@nonreentrant\n@view",
        "Override reentrancy mismatch: Override is non-reentrant, unlike the method it is"
        " overriding.",
        "remove the @nonreentrant decorator",
    ),
    (
        "@payable",
        "@nonreentrant\n@payable",
        "Override reentrancy mismatch: Override is non-reentrant, unlike the method it is"
        " overriding.",
        "remove the @nonreentrant decorator",
    ),
    # Combined decorator mismatches - mutability less strict
    (
        "@nonreentrant",
        "@nonreentrant\n@payable",
        "Override mutability mismatch: Got payable, but expected nonpayable (or stricter)",
        None,
    ),
    (
        "@nonreentrant\n@nonpayable",
        "@nonreentrant\n@payable",
        "Override mutability mismatch: Got payable, but expected nonpayable (or stricter)",
        None,
    ),
    (
        "@nonreentrant\n@view",
        "@nonreentrant\n@nonpayable",
        "Override mutability mismatch: Got nonpayable, but expected view (or stricter)",
        None,
    ),
    (
        "@nonreentrant\n@view",
        "@nonreentrant\n@payable",
        "Override mutability mismatch: Got payable, but expected view (or stricter)",
        None,
    ),
]


@pytest.mark.parametrize(
    "abstract_decorators,override_decorators,expected_message,expected_hint",
    INVALID_DECORATOR_OVERRIDES,
)
def test_decorator_override_invalid(
    get_contract,
    make_input_bundle,
    abstract_decorators,
    override_decorators,
    expected_message,
    expected_hint,
):
    """Test invalid decorator overrides (including mutability and nonreentrant)"""

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
        get_contract(contract, input_bundle=input_bundle)

    assert e.value.message == expected_message
    assert e.value.hint == expected_hint


def test_abstract_fails_on_external_functions(get_contract):
    """Test that @abstract decorator fails on @external functions"""
    contract = """
@external
@abstract
def test() -> uint256: ...
    """

    with pytest.raises(FunctionDeclarationException) as e:
        get_contract(contract)
    assert e.value.message == "@abstract decorator is not allowed on external functions"


def test_abstract_fails_on_deploy_functions(get_contract):
    """Test that @abstract decorator fails on @deploy functions"""
    contract = """
@deploy
@abstract
def __init__(): ...
    """

    with pytest.raises(FunctionDeclarationException) as e:
        get_contract(contract)
    assert e.value.message == "@abstract decorator is not allowed on deploy functions"


def test_override_fails_on_external_functions(get_contract, make_input_bundle):
    """Test that @override decorator fails on @external functions"""
    contract = """
import foo

initializes: foo

@external
@override(foo)
def test() -> uint256:
    return 42
    """

    foo = """
@abstract
def test() -> uint256: ...
    """

    input_bundle = make_input_bundle({"foo.vy": foo})

    with pytest.raises(FunctionDeclarationException) as e:
        get_contract(contract, input_bundle=input_bundle)
    assert e.value.message == "@override decorator is not allowed on external functions"


@pytest.mark.parametrize("with_abstract", [True, False])
def test_override_fails_on_deploy_functions(get_contract, make_input_bundle, with_abstract):
    """Test that @override decorator fails on @deploy functions"""

    optional_abstract = "@abstract" if with_abstract else ""

    contract = """
import foo

initializes: foo

@deploy
@override(foo)
def __init__():
    pass
    """

    foo = f"""
{optional_abstract}
@deploy
def __init__(): ...
    """

    input_bundle = make_input_bundle({"foo.vy": foo})

    with pytest.raises(FunctionDeclarationException) as e:
        get_contract(contract, input_bundle=input_bundle)

    if with_abstract:
        # fails on the abstract before it has a chance to fail on the override
        assert e.value.message == "@abstract decorator is not allowed on deploy functions"
    else:
        # fails on the missing abstract before it has a chance to fail on the override
        assert e.value.message == "Cannot override `__init__` from `foo` - method is not abstract"


def test_override_non_initialized_module_fails(get_contract, make_input_bundle):
    """Test that overriding from a non-initialized module fails with proper error"""
    contract = """
import foo
# Missing: initializes: foo

@override(foo)
def bar() -> uint256:
    return 42
    """

    foo = """
@abstract
def bar() -> uint256: ...
    """

    input_bundle = make_input_bundle({"foo.vy": foo})

    with pytest.raises(FunctionDeclarationException) as e:
        get_contract(contract, input_bundle=input_bundle)

    assert e.value.message == "Cannot override method from `foo` - module is not initialized"
    assert e.value.hint == "add `initializes: foo` as a top-level statement to your contract"


def test_override_non_abstract_method_fails(get_contract, make_input_bundle):
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
        get_contract(contract, input_bundle=input_bundle)

    assert e.value.message == "Cannot override `bar` from `foo` - method is not abstract"
    assert e.value.hint == "only abstract methods can be overridden"


def test_duplicate_override_fails(get_contract, make_input_bundle):
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
        get_contract(contract, input_bundle=input_bundle)

    assert e.value.message == "Method `some_method` from `foo` is already overridden"
    assert e.value.hint == "each abstract method can only be overridden once"


def test_override_validation_order(get_contract, make_input_bundle):
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
        get_contract(contract1, input_bundle=input_bundle1)

    # Should fail on non-initialized module before checking if method is abstract
    assert "module is not initialized" in e.value.message

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
        get_contract(contract2, input_bundle=input_bundle2)

    # Should fail on non-abstract method
    assert "method is not abstract" in e.value.message
