import pytest

from vyper import compiler
from vyper.compiler import compile_code
from vyper.exceptions import FunctionDeclarationException, StructureException, UndeclaredDefinition

FAILING_CONTRACTS = [
    (
        """
@external
@pure
@nonreentrant
def nonreentrant_foo() -> uint256:
    return 1
    """,
        StructureException,
    ),
    (
        """
@external
@nonreentrant
@nonreentrant
def nonreentrant_foo() -> uint256:
    return 1
    """,
        FunctionDeclarationException,
    ),
    (
        """
@external
@nonreentrant
@reentrant
def foo() -> uint256:
    return 1
    """,
        FunctionDeclarationException,
    ),
    (
        """
@external
@reentrant
@nonreentrant
def foo() -> uint256:
    return 1
    """,
        StructureException,
    ),
    (
        """
@external
@nonreentrant("foo")
def nonreentrant_foo() -> uint256:
    return 1
    """,
        StructureException,
    ),
    (
        """
@deploy
@nonreentrant
def __init__():
    pass
    """,
        FunctionDeclarationException,
    ),
    (
        """
@foo.bar
@external
def test():
    pass
    """,
        StructureException,
    ),
    (
        """
@foo.bar()
@external
def test():
    pass
    """,
        StructureException,
    ),
    (
        """
@abstract()
def foo():
    pass
    """,
        StructureException,
    ),
]


@pytest.mark.parametrize("bad_code,exc", FAILING_CONTRACTS)
def test_invalid_function_decorators(bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)


def test_invalid_function_decorator_vyi():
    code = """
@nonreentrant
def foo():
    ...
    """
    with pytest.raises(FunctionDeclarationException):
        compiler.compile_code(code, contract_path="foo.vyi", output_formats=["abi"])


def test_abstract_fails_on_external_functions():
    """Test that @abstract decorator fails on @external functions"""
    contract = """
@external
@abstract
def test() -> uint256: ...
    """

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract)
    assert e.value.message == "@abstract decorator is not allowed on external functions"


def test_abstract_fails_on_deploy_functions():
    """Test that @abstract decorator fails on @deploy functions"""
    contract = """
@deploy
@abstract
def __init__(): ...
    """

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract)
    assert e.value.message == "@abstract decorator is not allowed on deploy functions"


def test_override_fails_on_external_functions(make_input_bundle):
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
        compile_code(contract, input_bundle=input_bundle)
    assert e.value.message == "@override decorator is not allowed on external functions"


@pytest.mark.parametrize("with_abstract", [True, False])
def test_override_fails_on_deploy_functions(make_input_bundle, with_abstract):
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
        compile_code(contract, input_bundle=input_bundle)

    if with_abstract:
        # fails on the abstract before it has a chance to fail on the override
        assert e.value.message == "@abstract decorator is not allowed on deploy functions"
    else:
        # fails on the @override decorator validation
        assert e.value.message == "@override decorator is not allowed on deploy functions"


OVERRIDE_NON_MODULE_CASES = [
    """
struct MyStruct:
    value: uint256

@override(MyStruct)
def bar() -> uint256:
    return 42
    """,
    """
flag Status:
    IDLE
    RUNNING

@override(Status)
def bar() -> uint256:
    return 42
    """,
    """
event MyEvent:
    value: uint256

@override(MyEvent)
def bar() -> uint256:
    return 42
    """,
    """
interface IFoo:
    def foo() -> uint256: nonpayable

@override(IFoo)
def bar() -> uint256:
    return 42
    """,
    """
MY_CONST: constant(uint256) = 123

@override(MY_CONST)
def bar() -> uint256:
    return 42
        """,
]


@pytest.mark.parametrize("contract_code", OVERRIDE_NON_MODULE_CASES)
def test_override_non_module_fails(contract_code):
    """Test that @override on a non-module fails with proper error"""
    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract_code)

    # Expected error message pattern (to be implemented)
    assert "not a module" in e.value.message or "is not a module" in e.value.message


@pytest.mark.parametrize("invalid_arg", ["1", '"hello"', "foo.bar", "foo + bar"])
def test_override_invalid_argument_type(make_input_bundle, invalid_arg):
    """
    Test that @override() with non-identifier arguments raises StructureException
    """
    abstract_m = """
@abstract
def bar() -> uint256: ...
    """

    contract = f"""
import abstract_m
initializes: abstract_m

@override({invalid_arg})
def bar() -> uint256:
    return 42
    """

    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m})

    with pytest.raises(StructureException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert "@override argument must be a module identifier" in str(e.value)


def test_override_zero_arguments(make_input_bundle):
    """Test that @override() with no arguments raises StructureException"""
    abstract_m = """
@abstract
def bar() -> uint256: ...
    """
    contract = """
import abstract_m
initializes: abstract_m

@override()
def bar() -> uint256:
    return 42
    """
    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m})
    with pytest.raises(StructureException) as e:
        compile_code(contract, input_bundle=input_bundle)
    assert "@override takes an argument (the module containing the method to override)" in str(
        e.value
    )


def test_override_no_arguments(make_input_bundle):
    """Test that @override raises StructureException"""
    abstract_m = """
@abstract
def bar() -> uint256: ...
    """
    contract = """
import abstract_m
initializes: abstract_m

@override
def bar() -> uint256:
    return 42
    """
    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m})
    with pytest.raises(StructureException) as e:
        compile_code(contract, input_bundle=input_bundle)
    assert "@override takes an argument (the module containing the method to override)" in str(
        e.value
    )


@pytest.mark.parametrize("args", ["abstract_m, abstract_m", "a, b, c"])
def test_override_multiple_arguments(make_input_bundle, args):
    """Test that @override() with 2+ arguments raises StructureException"""
    abstract_m = """
@abstract
def bar() -> uint256: ...
    """
    contract = f"""
import abstract_m
initializes: abstract_m

@override({args})
def bar() -> uint256:
    return 42
    """
    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m})
    with pytest.raises(StructureException) as e:
        compile_code(contract, input_bundle=input_bundle)
    assert "@override takes a single argument" in str(e.value)


INTERFACE_BLOCK_DECORATOR_TESTS = [
    # decorator, expected_message
    ("@abstract", "Function definition in interface cannot be decorated"),
    ("@override(test_interface)", "Function definition in interface cannot be decorated"),
]


@pytest.mark.parametrize("decorator,expected_message", INTERFACE_BLOCK_DECORATOR_TESTS)
def test_decorators_not_allowed_in_interface_blocks(decorator, expected_message):
    """Test that @abstract and @override decorators are not allowed in interface blocks"""

    contract = f"""
interface test_interface:
    {decorator}
    def test_method() -> uint256: view
    """

    with pytest.raises(StructureException) as e:
        compile_code(contract)

    assert expected_message in str(e.value)


VYI_FILE_DECORATOR_TESTS = [
    # decorator, expected_message
    ("@abstract", "`@abstract` decorator not allowed in interfaces"),
    ("@override(test_interface)", "`@override` decorator not allowed in interfaces"),
]


@pytest.mark.parametrize("decorator,expected_message", VYI_FILE_DECORATOR_TESTS)
def test_decorators_not_allowed_in_vyi_files(make_input_bundle, decorator, expected_message):
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
        compile_code(contract, input_bundle=input_bundle)

    assert expected_message in str(e.value)


def test_override_undefined_module():
    """Test that @override() with an undefined module name raises UndeclaredDefinition"""
    contract = """
@override(nonexistent_module)
def bar() -> uint256:
    return 42
    """
    with pytest.raises(UndeclaredDefinition) as e:
        compile_code(contract)
    assert "'nonexistent_module' has not been declared" in str(e.value)


def test_override_module_not_imported(make_input_bundle):
    """Test that @override() referencing a module that exists but wasn't imported raises error"""
    abstract_m = """
@abstract
def bar() -> uint256: ...
    """
    # Module exists in bundle but is NOT imported in contract
    contract = """
@override(abstract_m)
def bar() -> uint256:
    return 42
    """
    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m})
    with pytest.raises(UndeclaredDefinition) as e:
        compile_code(contract, input_bundle=input_bundle)
    assert "'abstract_m' has not been declared" in str(e.value)
