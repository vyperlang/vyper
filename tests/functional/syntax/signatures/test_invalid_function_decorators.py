import pytest

from vyper import compiler
from vyper.exceptions import FunctionDeclarationException, StructureException

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
        # nonreentrant on an internal function
        """
@nonreentrant
def foo():
    pass
    """,
        FunctionDeclarationException,
    ),
    (
        # nonreentrant on an internal function
        """
@internal
@nonreentrant
def foo():
    pass
    """,
        FunctionDeclarationException,
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
