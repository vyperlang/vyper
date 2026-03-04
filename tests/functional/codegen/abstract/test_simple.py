import pytest

from vyper.exceptions import (
    ArgumentException,
    CallViolation,
    FunctionDeclarationException,
    ImmutableViolation,
    InitializerException,
    StructureException,
    VyperException,
)


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

uses: abstract_m
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
    expected_msg = "abstract_m.vy` is used but never initialized!"
    assert expected_msg in e.value.message
    expected_hint = "add `initializes: abstract_m`"
    assert expected_hint in e.value.hint


def test_stateful_override_with_initializes(get_contract, make_input_bundle):
    # Test that the same contract works when override_m is properly initialized
    contract = """
import abstract_m
import override_m

uses: abstract_m
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


def test_call_to_abstract_without_uses(get_contract, make_input_bundle):
    # Test that the same contract works when override_m is properly initialized
    contract = """
import abstract_m
import override_m

# uses: abstract_m
initializes: override_m

@external
def my_method() -> uint256:
    return abstract_m.bar() # Call to abstract method from un-uses-ed module
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

    with pytest.raises(ImmutableViolation) as e:
        get_contract(contract, input_bundle=input_bundle)

    # TODO: Should be a better error message
    assert "Cannot access `abstract_m` state!" in e.value.message


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
    # === ADDING OPTIONAL PARAMETERS ===
    # Override adds optional parameter to abstract with no parameters
    ("x: uint256 = 100", "uint256", "x", "", "uint256", "", 100),
    # Override adds optional parameter to abstract with one parameter
    ("x: uint256, y: uint256 = 50", "uint256", "x + y", "x: uint256", "uint256", "10", 60),
    # Override adds multiple optional parameters
    (
        "x: uint256, y: uint256 = 20, z: uint256 = 30",
        "uint256",
        "x + y + z",
        "x: uint256",
        "uint256",
        "10",
        60,
    ),
    # Override makes mandatory parameter optional (allowed - more permissive)
    (
        "x: uint256, y: uint256 = 10",
        "uint256",
        "x + y",
        "x: uint256, y: uint256",
        "uint256",
        "5, 15",
        20,
    ),
    # === ABSTRACT METHODS WITH OPTIONAL PARAMETERS ===
    # Abstract method with non-valued default parameter
    (
        "x: uint256, y: uint256 = 10",
        "uint256",
        "x + y",
        "x: uint256, y: uint256 = ...",
        "uint256",
        "5, 15",
        20,
    ),
    # Abstract method with valued default
    (
        "x: uint256, y: uint256 = 10",
        "uint256",
        "x + y",
        "x: uint256, y: uint256 = 10",
        "uint256",
        "5, 15",
        20,
    ),
    # === SEMANTIC DEFAULT VALUE MATCHING ===
    # Environment variable default matching (msg.sender)
    (
        "x: uint256, a: address = msg.sender",
        "address",
        "a",
        "x: uint256, a: address = msg.sender",
        "address",
        "1",
        None,  # Will be msg.sender
    ),
    # Environment variable default matching (block.number)
    (
        "x: uint256, b: uint256 = block.number",
        "uint256",
        "b",
        "x: uint256, b: uint256 = block.number",
        "uint256",
        "1",
        None,  # Will be block.number
    ),
    # === ADDITIONAL DEFAULT EXPRESSION TYPES ===
    # Boolean literal default
    (
        "x: uint256, flag: bool = True",
        "bool",
        "flag",
        "x: uint256, flag: bool = True",
        "bool",
        "1",
        True,
    ),
    # Address literal default
    (
        "x: uint256, addr: address = 0x0000000000000000000000000000000000012345",
        "address",
        "addr",
        "x: uint256, addr: address = 0x0000000000000000000000000000000000012345",
        "address",
        "1",
        "0x0000000000000000000000000000000000012345",
    ),
    # Array literal default
    (
        "x: uint256, arr: uint256[2] = [10, 20]",
        "uint256",
        "arr[0] + arr[1]",
        "x: uint256, arr: uint256[2] = [10, 20]",
        "uint256",
        "1",
        30,
    ),
    # Power expression default (2**8)
    (
        "x: uint256, val: uint256 = 2**8",
        "uint256",
        "val",
        "x: uint256, val: uint256 = 2**8",
        "uint256",
        "1",
        256,
    ),
    # Built-in function default: empty()
    (
        "x: uint256, addr: address = empty(address)",
        "address",
        "addr",
        "x: uint256, addr: address = empty(address)",
        "address",
        "1",
        "0x" + "00" * 20,
    ),
    # Built-in function default: min_value()
    (
        "x: uint256, val: int128 = min_value(int128)",
        "int128",
        "val",
        "x: uint256, val: int128 = min_value(int128)",
        "int128",
        "1",
        -(2**127),
    ),
    # Bytes literal default (bytes4)
    (
        "x: uint256, data: bytes4 = 0xdeadbeef",
        "bytes4",
        "data",
        "x: uint256, data: bytes4 = 0xdeadbeef",
        "bytes4",
        "1",
        b"\xde\xad\xbe\xef",
    ),
    # tx.origin environment variable
    (
        "x: uint256, origin: address = tx.origin",
        "address",
        "origin",
        "x: uint256, origin: address = tx.origin",
        "address",
        "1",
        None,  # Will be tx.origin
    ),
    # block.coinbase environment variable
    (
        "x: uint256, coinbase: address = block.coinbase",
        "address",
        "coinbase",
        "x: uint256, coinbase: address = block.coinbase",
        "address",
        "1",
        None,  # Will be block.coinbase
    ),
    # block.timestamp environment variable
    (
        "x: uint256, ts: uint256 = block.timestamp",
        "uint256",
        "ts",
        "x: uint256, ts: uint256 = block.timestamp",
        "uint256",
        "1",
        None,  # Will be block.timestamp
    ),
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
        "Override has mandatory parameter `y: uint256` not present in the abstract method.",
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
    # Parameters swapped (same names and types but wrong positions)
    # Uses VyperException because both parameters mismatch, resulting in multiple errors
    (
        "y: uint256, x: uint256",
        "uint256",
        "x + y",
        "x: uint256, y: uint256",
        "uint256",
        VyperException,
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
    # === ABSTRACT METHODS WITH OPTIONAL PARAMETERS ===
    # Abstract method with mismatch in default parameter value
    (
        "x: uint256, y: uint256 = 20",
        "uint256",
        "x + y",
        "x: uint256, y: uint256 = 10",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # Optional parameter in abstract cannot be mandatory in override
    (
        "x: uint256, y: uint256",
        "uint256",
        "x + y",
        "x: uint256, y: uint256 = ...",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # === DIFFERENT DEFAULT VALUES ===
    # Different environment variables (msg.sender vs tx.origin)
    (
        "x: uint256, a: address = tx.origin",
        "address",
        "a",
        "x: uint256, a: address = msg.sender",
        "address",
        FunctionDeclarationException,
        "Override parameter mismatch",
    ),
    # Different environment variables (block.number vs block.timestamp)
    (
        "x: uint256, b: uint256 = block.timestamp",
        "uint256",
        "b",
        "x: uint256, b: uint256 = block.number",
        "uint256",
        FunctionDeclarationException,
        "Override parameter mismatch",
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

    def replace_ellipsis_defaults(params: str) -> str:
        if not params:
            return ""
        param_list = []
        for param in params.split(","):
            param = param.strip()
            if "= ..." in param:
                param = param.replace("= ...", "= 0")
            param_list.append(param)
        return ", ".join(param_list)

    param_names = extract_param_names(params_abstract)
    forwarder_params = replace_ellipsis_defaults(params_abstract)

    foo = f"""
def forwarder({forwarder_params}){with_arrow(return_type_abstract)}:
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


def test_uninitialized_abstract_call_fails(get_contract, make_input_bundle):
    abstract_module = """
@abstract
def foo() -> uint256: ...
    """

    override_module = """
import abstract_module

initializes: abstract_module

@override(abstract_module)
def foo() -> uint256:
    return 42
    """

    contract = """
import override_module
import abstract_module

uses: abstract_module
# initializes: override_module # Without this, we have no way of knowing which override to pick

@external
def test_foo() -> uint256:
    return abstract_module.foo()
    """

    input_bundle = make_input_bundle(
        {"abstract_module.vy": abstract_module, "override_module.vy": override_module}
    )

    with pytest.raises(InitializerException) as e:
        get_contract(contract, input_bundle=input_bundle)

    assert "abstract_module.vy` is used but never initialized!" in e.value.message
    assert "add `initializes: abstract_module`" in e.value.hint


def test_three_level_override_chain(get_contract, make_input_bundle):
    """Test chain of overrides: A.foo overrides B.foo which overrides C.foo"""

    module_c = """
@abstract
def foo() -> uint256: ...
    """

    module_b = """
import module_c

initializes: module_c

@abstract
@override(module_c)
def foo() -> uint256: ...
    """

    module_a = """
import module_b

initializes: module_b

@override(module_b)
def foo() -> uint256:
    return 42
    """

    contract = """
import module_a
import module_c

initializes: module_a
uses: module_c

@external
def test_foo() -> uint256:
    # Can call through module_c and get A's implementation
    return module_c.foo()
    """

    input_bundle = make_input_bundle(
        {"module_c.vy": module_c, "module_b.vy": module_b, "module_a.vy": module_a}
    )

    c = get_contract(contract, input_bundle=input_bundle)
    assert c.test_foo() == 42


def test_override_with_default_param_changes_signature(get_contract, make_input_bundle):
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
        get_contract(contract, input_bundle=input_bundle)

    assert "Invalid argument count for call to 'foo': expected 0, got 1" in str(e.value)


def test_override_optional_param_still_mandatory_via_abstract(get_contract, make_input_bundle):
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
        get_contract(contract, input_bundle=input_bundle)

    assert "Invalid argument count for call to 'foo': expected 2, got 1" in str(e.value)


def test_method_overrides_multiple_abstracts(get_contract, make_input_bundle):
    """Test that a method can override multiple abstract methods from different modules"""

    abstract_module_a = """
@abstract
def common_method() -> uint256: ...
    """

    abstract_module_b = """
@abstract
def common_method() -> uint256: ...
    """

    override_module = """
import abstract_module_a
import abstract_module_b

initializes: abstract_module_a
initializes: abstract_module_b

@override(abstract_module_a)
@override(abstract_module_b)
def common_method() -> uint256:
    return 100
    """

    contract = """
import abstract_module_a
import abstract_module_b
import override_module

uses: abstract_module_a
uses: abstract_module_b
initializes: override_module

@external
def test_a() -> uint256:
    return abstract_module_a.common_method()

@external
def test_b() -> uint256:
    return abstract_module_b.common_method()
    """

    input_bundle = make_input_bundle(
        {
            "abstract_module_a.vy": abstract_module_a,
            "abstract_module_b.vy": abstract_module_b,
            "override_module.vy": override_module,
        }
    )

    c = get_contract(contract, input_bundle=input_bundle)
    assert c.test_a() == 100
    assert c.test_b() == 100


def test_method_overrides_multiple_abstracts_signature_match(get_contract, make_input_bundle):
    """Test that overriding multiple abstracts fails if signatures don't match"""

    abstract_module_a = """
@abstract
def common_method() -> uint256: ...
    """

    abstract_module_b = """
@abstract
def common_method(x: uint256) -> uint256: ...
    """

    override_module = """
import abstract_module_a
import abstract_module_b

initializes: abstract_module_a
initializes: abstract_module_b

@override(abstract_module_a)
@override(abstract_module_b)
def common_method(x: uint256 = 100) -> uint256:
    return x
    """

    contract = """
import abstract_module_a
import abstract_module_b
import override_module

uses: abstract_module_a
uses: abstract_module_b
initializes: override_module

@external
def test1() -> uint256:
    return abstract_module_a.common_method()

@external
def test2(x: uint256) -> uint256:
    return abstract_module_b.common_method(x)
    """

    input_bundle = make_input_bundle(
        {
            "abstract_module_a.vy": abstract_module_a,
            "abstract_module_b.vy": abstract_module_b,
            "override_module.vy": override_module,
        }
    )

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.test1() == 100
    assert c.test2(1) == 1
    assert c.test2(42) == 42


def test_overriding_module_can_use_state(get_contract, make_input_bundle):
    stateful = """
counter: uint256

def increment():
    self.counter += 1

def get_counter() -> uint256:
    return self.counter
    """

    b_module = """
import stateful

initializes: stateful

def biased(bias: uint256) -> uint256:
    return stateful.get_counter() + bias

@abstract
def process() -> uint256: ...
    """

    a_module = """
import stateful
import b_module

uses: stateful        # If this was not possible, there would be an issue
initializes: b_module

@override(b_module)
def process() -> uint256:
    stateful.increment()
    return stateful.get_counter()
    """

    contract = """
import stateful
import a_module
import b_module

uses: b_module
initializes: a_module[stateful := stateful]

@external
def test_multiple_calls() -> uint256:
    b_module.process()
    b_module.process()
    return b_module.process()
    """

    input_bundle = make_input_bundle(
        {"stateful.vy": stateful, "b_module.vy": b_module, "a_module.vy": a_module}
    )

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.test_multiple_calls() == 3


INTERFACE_BLOCK_DECORATOR_TESTS = [
    # decorator, expected_message
    ("@abstract", "Function definition in interface cannot be decorated"),
    ("@override(test_interface)", "Function definition in interface cannot be decorated"),
]


@pytest.mark.parametrize("decorator,expected_message", INTERFACE_BLOCK_DECORATOR_TESTS)
def test_decorators_not_allowed_in_interface_blocks(get_contract, decorator, expected_message):
    """Test that @abstract and @override decorators are not allowed in interface blocks"""

    contract = f"""
interface test_interface:
    {decorator}
    def test_method() -> uint256: view
    """

    with pytest.raises(StructureException) as e:
        get_contract(contract)

    assert expected_message in str(e.value)


VYI_FILE_DECORATOR_TESTS = [
    # decorator, expected_message
    ("@abstract", "`@abstract` decorator not allowed in interfaces"),
    ("@override(test_interface)", "`@override` decorator not allowed in interfaces"),
]


@pytest.mark.parametrize("decorator,expected_message", VYI_FILE_DECORATOR_TESTS)
def test_decorators_not_allowed_in_vyi_files(
    get_contract, make_input_bundle, decorator, expected_message
):
    """Test that @abstract and @override decorators are not allowed in .vyi interface files"""

    interface_file = f"""
{decorator}
@external
def test_method() -> uint256: ...
    """

    contract = """
import test_interface

@external
def test() -> uint256:
    return test_interface.test_method()
    """

    input_bundle = make_input_bundle({"test_interface.vyi": interface_file})

    with pytest.raises(FunctionDeclarationException) as e:
        get_contract(contract, input_bundle=input_bundle)

    assert expected_message in str(e.value)


def test_overriding_module_can_initialize_state(get_contract, make_input_bundle):
    stateful = """
counter: uint256

def increment():
    self.counter += 1

def get_counter() -> uint256:
    return self.counter
    """

    b_module = """
# if the following was needed, it would severely limit the usefulness of the feature
# uses: stateful

@abstract
def process() -> uint256: ...
    """

    a_module = """
import stateful
import b_module

initializes: stateful
initializes: b_module

@override(b_module)
def process() -> uint256:
    stateful.increment()
    return stateful.get_counter()
    """

    contract = """
import stateful
import a_module
import b_module

uses: b_module
initializes: a_module

@external
def test_multiple_calls() -> uint256:
    b_module.process()
    b_module.process()
    return b_module.process()
    """

    input_bundle = make_input_bundle(
        {"stateful.vy": stateful, "b_module.vy": b_module, "a_module.vy": a_module}
    )

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.test_multiple_calls() == 3


def test_override_recursion_fails(get_contract, make_input_bundle):
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
        get_contract(contract, input_bundle=input_bundle)

    # TODO: Maybe improve error message so it includes overrides ?
    # Something like a.foo -> b.forwarder -> b.foo -resolves_to-> a.foo
    # Note: The cycle can be detected starting from either function depending on processing order
    assert (
        "Contract contains cyclic function call: forwarder -> foo -> forwarder" == e.value.message
    )


OVERRIDE_DEFAULT_PARAM_CALLS = [
    (
        "x: uint256, y: uint256 = ...",
        "x: uint256, y: uint256 = 10",
        [("x: uint256", "x", (5,), 15), ("x: uint256, y: uint256", "x, y", (5, 20), 25)],
    ),
    (
        "x: uint256, y: uint256 = 10",
        "x: uint256, y: uint256 = 10",
        [("x: uint256", "x", (5,), 15), ("x: uint256, y: uint256", "x, y", (5, 20), 25)],
    ),
    (
        "a: uint256, b: uint256 = ..., c: uint256 = ...",
        "a: uint256, b: uint256 = 10, c: uint256 = 20",
        [
            ("a: uint256", "a", (5,), 35),
            ("a: uint256, b: uint256", "a, b", (5, 15), 40),
            ("a: uint256, b: uint256, c: uint256", "a, b, c", (5, 15, 25), 45),
        ],
    ),
]


@pytest.mark.parametrize("test_case", OVERRIDE_DEFAULT_PARAM_CALLS)
def test_override_default_params_direct_call(get_contract, make_input_bundle, test_case):
    """Test calling an override directly with default parameters."""
    params_abstract, params_override, call_variations = test_case

    if params_override.startswith("x:"):
        return_expr = "x + y"
    else:
        return_expr = "a + b + c"

    abstract_mod = f"""
@abstract
def bar({params_abstract}) -> uint256: ...
    """

    for call_bar_params, call_to_bar, call_bar_args, expected in call_variations:
        contract = f"""
import abstract_mod

initializes: abstract_mod

@external
def call_bar({call_bar_params}) -> uint256:
    return self.bar({call_to_bar})

@override(abstract_mod)
def bar({params_override}) -> uint256:
    return {return_expr}
        """

        input_bundle = make_input_bundle({"abstract_mod.vy": abstract_mod})
        c = get_contract(contract, input_bundle=input_bundle)

        assert c.call_bar(*call_bar_args) == expected


def test_must_override_all_abstract_methods(get_contract, make_input_bundle):
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
        get_contract(contract, input_bundle=input_bundle)

    assert "Abstract function was not overridden" == e.value.message
    assert "bar" in e.value.annotations[0].node_source_code


def test_contract_cannot_have_abstract_methods(get_contract):
    """Test that a top-level contract cannot have abstract methods"""

    contract = """
@abstract
def foo() -> uint256: ...

@external
def bar() -> uint256:
    return self.foo()
    """

    with pytest.raises(FunctionDeclarationException) as e:
        get_contract(contract)

    assert "Abstract function was not overridden" == e.value.message
    assert "foo" in e.value.annotations[0].node_source_code


def test_cannot_call_overridden_method(get_contract, make_input_bundle):
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
        get_contract(contract, input_bundle=input_bundle)

    assert "foo" in e.value.message


def test_abstract_method_body_must_be_ellipsis(get_contract, make_input_bundle):
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
        get_contract(contract, input_bundle=input_bundle)

    assert "abstract" in e.value.message.lower()


def test_abstract_method_with_docstring_succeeds(get_contract, make_input_bundle):
    """Test that abstract method can have a docstring before ..."""

    abstract_module = '''
@abstract
def foo() -> uint256:
    """This is a docstring for the abstract method."""
    ...
    '''

    contract = """
import abstract_module

initializes: abstract_module

@external
def test() -> uint256:
    return abstract_module.foo()

@override(abstract_module)
def foo() -> uint256:
    return 42
    """

    input_bundle = make_input_bundle({"abstract_module.vy": abstract_module})

    # Should compile successfully
    c = get_contract(contract, input_bundle=input_bundle)
    assert c.test() == 42


def test_uses_clause_does_not_allow_override(get_contract, make_input_bundle):
    """Test that a module with only uses clause cannot override abstract methods"""

    abstract_module = """
@abstract
def foo() -> uint256: ...
    """

    contract = """
import abstract_module

uses: abstract_module  # Only uses, not initializes

@override(abstract_module)  # Should fail - can't override from uses-only
def foo() -> uint256:
    return 100
    """

    input_bundle = make_input_bundle({"abstract_module.vy": abstract_module})

    with pytest.raises(FunctionDeclarationException) as e:
        get_contract(contract, input_bundle=input_bundle)

    assert "not initialized" in e.value.message


def test_module_override_without_initializing(get_contract, make_input_bundle):
    """Test that a module cannot override from another module it doesn't initialize"""

    abstract_module = """
@abstract
def foo() -> uint256: ...
    """

    override_module = """
import abstract_module

uses: abstract_module  # Only uses, not initializes

@override(abstract_module)  # Should fail
def foo() -> uint256:
    return 42
    """

    contract = """
import override_module
import abstract_module

initializes: abstract_module
initializes: override_module
    """

    input_bundle = make_input_bundle(
        {"abstract_module.vy": abstract_module, "override_module.vy": override_module}
    )

    with pytest.raises(FunctionDeclarationException) as e:
        get_contract(contract, input_bundle=input_bundle)

    assert "not initialized" in e.value.message


def test_ellipsis_cannot_override_concrete_default_parameter(get_contract, make_input_bundle):
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
        get_contract(contract, input_bundle=input_bundle)

    assert "Override parameter mismatch" in e.value.message


def test_different_import_same_name_default_mismatch(get_contract, make_input_bundle):
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
        get_contract(main_contract, input_bundle=input_bundle)

    assert "Override parameter mismatch" in e.value.message


def test_default_param_constant_reference_override(get_contract, make_input_bundle):
    """Test override with constant reference default parameter - both use same constant"""

    constants_lib = """
FOO: constant(uint256) = 42
    """

    abstract_module = """
import constants_lib

@abstract
def bar(x: uint256 = constants_lib.FOO) -> uint256: ...
    """

    override_contract = """
import abstract_module
import constants_lib

initializes: abstract_module

@external
def call_bar() -> uint256:
    return self.bar()

@override(abstract_module)
def bar(x: uint256 = constants_lib.FOO) -> uint256:
    return x
    """

    input_bundle = make_input_bundle(
        {"constants_lib.vy": constants_lib, "abstract_module.vy": abstract_module}
    )

    c = get_contract(override_contract, input_bundle=input_bundle)
    assert c.call_bar() == 42


def test_default_param_struct_instantiation_override(get_contract, make_input_bundle):
    """Test override with struct instantiation default parameter"""

    types_lib = """
struct Point:
    x: uint256
    y: uint256
    """

    abstract_module = """
import types_lib

@abstract
def process(p: types_lib.Point = types_lib.Point(x=10, y=20)) -> uint256: ...
    """

    override_contract = """
import abstract_module
import types_lib

initializes: abstract_module

@external
def call_process() -> uint256:
    return self.process()

@override(abstract_module)
def process(p: types_lib.Point = types_lib.Point(x=10, y=20)) -> uint256:
    return p.x + p.y
    """

    input_bundle = make_input_bundle(
        {"types_lib.vy": types_lib, "abstract_module.vy": abstract_module}
    )

    c = get_contract(override_contract, input_bundle=input_bundle)
    assert c.call_process() == 30


def test_default_param_arithmetic_expression_override(get_contract, make_input_bundle):
    """Test override with arithmetic expression default parameter"""

    constants_lib = """
BASE: constant(uint256) = 100
    """

    abstract_module = """
import constants_lib

@abstract
def calc(x: uint256 = constants_lib.BASE + 5) -> uint256: ...
    """

    override_contract = """
import abstract_module
import constants_lib

initializes: abstract_module

@external
def call_calc() -> uint256:
    return self.calc()

@override(abstract_module)
def calc(x: uint256 = constants_lib.BASE + 5) -> uint256:
    return x
    """

    input_bundle = make_input_bundle(
        {"constants_lib.vy": constants_lib, "abstract_module.vy": abstract_module}
    )

    c = get_contract(override_contract, input_bundle=input_bundle)
    assert c.call_calc() == 105


def test_default_param_bool_operation_override(get_contract, make_input_bundle):
    """Test override with boolean operation default parameter"""

    constants_lib = """
FLAG_A: constant(bool) = True
FLAG_B: constant(bool) = False
    """

    abstract_module = """
import constants_lib

@abstract
def check(flag: bool = constants_lib.FLAG_A and not constants_lib.FLAG_B) -> bool: ...
    """

    override_contract = """
import abstract_module
import constants_lib

initializes: abstract_module

@external
def call_check() -> bool:
    return self.check()

@override(abstract_module)
def check(flag: bool = constants_lib.FLAG_A and not constants_lib.FLAG_B) -> bool:
    return flag
    """

    input_bundle = make_input_bundle(
        {"constants_lib.vy": constants_lib, "abstract_module.vy": abstract_module}
    )

    c = get_contract(override_contract, input_bundle=input_bundle)
    assert c.call_check() is True


def test_default_param_comparison_expression_override(get_contract, make_input_bundle):
    """Test override with comparison expression default parameter"""

    constants_lib = """
THRESHOLD: constant(uint256) = 100
    """

    abstract_module = """
import constants_lib

@abstract
def is_above(result: bool = constants_lib.THRESHOLD > 50) -> bool: ...
    """

    override_contract = """
import abstract_module
import constants_lib

initializes: abstract_module

@external
def call_is_above() -> bool:
    return self.is_above()

@override(abstract_module)
def is_above(result: bool = constants_lib.THRESHOLD > 50) -> bool:
    return result
    """

    input_bundle = make_input_bundle(
        {"constants_lib.vy": constants_lib, "abstract_module.vy": abstract_module}
    )

    c = get_contract(override_contract, input_bundle=input_bundle)
    assert c.call_is_above() is True


def test_default_param_nested_struct_override(get_contract, make_input_bundle):
    """Test override with nested struct instantiation default parameter"""

    types_lib = """
struct Inner:
    value: uint256

struct Outer:
    inner: Inner
    extra: uint256
    """

    abstract_module = """
import types_lib

@abstract
def process(
    data: types_lib.Outer = types_lib.Outer(inner=types_lib.Inner(value=5),
    extra=10)
) -> uint256: ...
    """

    override_contract = """
import abstract_module
import types_lib

initializes: abstract_module

@external
def call_process() -> uint256:
    return self.process()

@override(abstract_module)
def process(
    data: types_lib.Outer = types_lib.Outer(inner=types_lib.Inner(value=5),
    extra=10)
) -> uint256:
    return data.inner.value + data.extra
    """

    input_bundle = make_input_bundle(
        {"types_lib.vy": types_lib, "abstract_module.vy": abstract_module}
    )

    c = get_contract(override_contract, input_bundle=input_bundle)
    assert c.call_process() == 15


def test_default_param_max_value_override(get_contract, make_input_bundle):
    """Test override with max_value() built-in default parameter"""

    abstract_module = """
@abstract
def get_max(val: uint8 = max_value(uint8)) -> uint8: ...
    """

    override_contract = """
import abstract_module

initializes: abstract_module

@external
def call_get_max() -> uint8:
    return self.get_max()

@override(abstract_module)
def get_max(val: uint8 = max_value(uint8)) -> uint8:
    return val
    """

    input_bundle = make_input_bundle({"abstract_module.vy": abstract_module})

    c = get_contract(override_contract, input_bundle=input_bundle)
    assert c.call_get_max() == 255
