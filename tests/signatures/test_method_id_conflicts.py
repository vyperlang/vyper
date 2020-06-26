import pytest

from vyper import compiler
from vyper.exceptions import StructureException

FAILING_CONTRACTS = [
    """
@public
@view
def gsf():
    pass

@public
@view
def tgeo():
    pass
    """,
    """
@public
@view
def withdraw(a: uint256):
    pass

@public
@view
def OwnerTransferV7b711143(a: uint256):
    pass
    """,
    """
@public
@view
def withdraw(a: uint256):
    pass

@public
@view
def gsf():
    pass

@public
@view
def tgeo():
    pass

@public
@view
def OwnerTransferV7b711143(a: uint256):
    pass
    """,
    """
# check collision between private method IDs
@private
@view
def gfah(): pass

@private
@view
def eexo(): pass
    """,
    """
# check collision between private and public IDs
@private
@view
def gfah(): pass

@public
@view
def eexo(): pass
    """,
]


@pytest.mark.parametrize("failing_contract_code", FAILING_CONTRACTS)
def test_method_id_conflicts(failing_contract_code):
    with pytest.raises(StructureException):
        compiler.compile_code(failing_contract_code)
