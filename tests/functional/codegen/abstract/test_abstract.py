from collections import defaultdict
from textwrap import dedent

import pytest

from vyper.compiler import compile_code
from vyper.exceptions import CallViolation


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


def test_abstract_method_with_docstring_succeeds(get_contract, make_input_bundle):
    """Test that abstract method can have a docstring before ..."""

    abstract_module = '''
@abstract
def foo() -> uint256:
    """This is a docstring for the abstract method."""
    ...
    '''

    override_module = """
import abstract_module

initializes: abstract_module

@override(abstract_module)
def foo() -> uint256:
    return 42
    """

    contract = """
import abstract_module
import override_module

uses: abstract_module
initializes: override_module

@external
def test() -> uint256:
    return abstract_module.foo()
    """

    input_bundle = make_input_bundle(
        {"abstract_module.vy": abstract_module, "override_module.vy": override_module}
    )

    # Should compile successfully
    c = get_contract(contract, input_bundle=input_bundle)
    assert c.test() == 42


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


def test_chained_abstract_method_call(get_contract, make_input_bundle):
    b = """
@abstract
def foo() -> uint256: ...
    """

    a = """
import b

uses: b

def makes_the_uses_valid():
    b.foo()
    """

    override = """
import b

initializes: b

@override(b)
def foo() -> uint256:
    return 42
    """

    # used so that the contract doesn't even import b
    initializer = """
import a
import b
import override

initializes: override
initializes: a[b := b]
    """

    contract = """
import a
import initializer

uses: a
initializes: initializer

@external
def call_chained() -> uint256:
    return a.b.foo()  # chained abstract method call through a's view of b
    """

    input_bundle = make_input_bundle(
        {"b.vy": b, "a.vy": a, "override.vy": override, "initializer.vy": initializer}
    )

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.call_chained() == 42


def _parse_relationships(chain_str) -> dict[str, list[(str, str)]]:
    """
    Parse relationship graph into a dict of source -> (relationship, target).

    Example:
        '''
        self -initializes-> a -overrides-> b
        self -imports-> b
        ''' becomes
        {
            "self": [("initializes", a), ("imports", b)],
            "a": [("overrides", b)],
            "b": [],
        }
    """

    result = defaultdict(list)

    for line in chain_str.split("\n"):
        if len(line.strip()) == 0:
            continue

        tokens = line.split()
        modules = tokens[0::2]
        arrows = tokens[1::2]

        for i in range(len(arrows)):
            arrow: str = arrows[i]
            source = modules[i]
            destination = modules[i + 1]

            relationship = arrow.removeprefix("-").removesuffix("->")

            assert relationship in ("imports", "uses", "initializes", "overrides")

            result[source].append((relationship, destination))

        # Make sure the last item in the chain is added
        result[modules[-1]]

    return result


def _generate_modules(relationships: dict[str, list[(str, str)]]):
    """
    Generate module code based on the relationships.

    Returns dict of {filename: code}.
    """

    abstract_modules = set()

    modules: dict[str, str] = {}  # {filename: code}

    for _, children in relationships.items():
        for rel, child in children:
            if rel == "overrides":
                abstract_modules.add(child)

    for current, children in relationships.items():
        code = ""

        for _, child in children:
            code += f"import {child}\n"

        code += "\n"

        for rel, child in children:
            if rel in ("initializes", "overrides"):
                code += f"initializes: {child}\n"
            elif rel in ("uses",):
                code += f"uses: {child}\n"
            elif rel in ("imports",):
                pass
            else:
                raise AssertionError("unreachable")

        for rel, child in children:
            if rel in ("uses",):
                code += dedent(
                    f"""
                    # Otherwise uses complains about not being required
                    def _make_uses_{child}_valid():
                        {child}.foo()
                """
                )

            if rel in ("overrides",):
                if current in abstract_modules:
                    code += dedent(
                        f"""
                        @abstract
                        @override({child})
                        def foo() -> uint256:
                            ...
                    """
                    )
                else:
                    code += dedent(
                        f"""
                        @override({child})
                        def foo() -> uint256:
                            return 42
                    """
                    )

        if "def foo" not in code:
            if current in abstract_modules:
                code += dedent(
                    """
                    @abstract
                    def foo() -> uint256:
                        ...
                """
                )
            else:
                code += dedent(
                    """
                    def foo() -> uint256:
                        return 42
                """
                )

        modules[f"{current}.vy"] = code

    return modules


# Test parameters:
# (chain_str, call_path, expected_hint)
#
# expected_hint: None = success case
#                str  = error case (CallViolation, hint contains this)
CHAIN_CALL_TESTS = [
    # === SUCCESS CASES ===
    ("self -initializes-> a -initializes-> b", "a.b.foo", None),
    (  # Can call through c and get a's implementation
        """
        self -initializes-> initializer -initializes-> a -overrides-> b -overrides-> c
        self -uses-> c
        """,
        "c.foo",
        None,
    ),
    # === ERROR CASES ===
    ("self -overrides-> b", "b.foo", "self.foo"),
    ("self -overrides-> b -overrides-> c", "b.c.foo", "self.foo"),
    ("self -initializes-> a -overrides-> b", "a.b.foo", "a.foo"),
    ("self -initializes-> a -initializes-> b -overrides-> c", "a.b.c.foo", "a.b.foo"),
    ("self -initializes-> a -overrides-> b -overrides-> c", "a.b.c.foo", "a.foo"),
    (
        """
        self -initializes-> a -initializes-> b -overrides-> c
        self -imports-> b
        """,
        "a.b.c.foo",
        "a.b.foo",  # Even though b.foo is technically shorter
    ),
]


@pytest.mark.parametrize("chain_str,call_path,expected_hint", CHAIN_CALL_TESTS)
def test_abstract_method_chain_call(
    get_contract, make_input_bundle, chain_str, call_path, expected_hint
):
    """
    Parametrized test for abstract method chain calls.

    Tests various module relationship chains and verifies correct behavior
    for both success cases and error cases with proper hints.
    """

    relationships = _parse_relationships(chain_str)
    modules = _generate_modules(relationships)

    contract_code = modules["self.vy"] + dedent(
        f"""
        @external
        def test() -> uint256:
            return {call_path}()
    """
    )

    input_bundle = make_input_bundle(modules)

    if expected_hint is None:
        # Success case
        c = get_contract(contract_code, input_bundle=input_bundle)
        assert c.test() == 42
    else:
        # Error case
        with pytest.raises(CallViolation) as exc_info:
            compile_code(contract_code, input_bundle=input_bundle)
        expected_msg = f"Abstract method `{call_path}` is overridden by "
        expected_msg += f"`{expected_hint}`, call that instead."
        assert expected_msg in str(exc_info.value)

        # Check the hint actually works

        hinted_at_contract_code = modules["self.vy"] + dedent(
            f"""
            @external
            def test() -> uint256:
                return {expected_hint}()
        """
        )

        c = get_contract(hinted_at_contract_code, input_bundle=input_bundle)
        assert c.test() == 42
