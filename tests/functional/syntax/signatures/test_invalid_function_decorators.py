import pytest

from vyper import compiler
from vyper.exceptions import StructureException

FAILING_CONTRACTS = [
    """
@external
@pure
@nonreentrant
def nonreentrant_foo() -> uint256:
    return 1
    """,
    """
@external
@nonreentrant
@nonreentrant
def nonreentrant_foo() -> uint256:
    return 1
    """,
    """
@external
@nonreentrant("foo")
def nonreentrant_foo() -> uint256:
    return 1
    """,
]


@pytest.mark.parametrize("failing_contract_code", FAILING_CONTRACTS)
def test_invalid_function_decorators(failing_contract_code):
    with pytest.raises(StructureException):
        compiler.compile_code(failing_contract_code)
