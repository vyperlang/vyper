import pytest

from vyper import compiler
from vyper.exceptions import StructureException

FAILING_CONTRACTS = [
    """
@public
@constant
def gsf():
    pass

@public
@constant
def tgeo():
    pass
    """,
    """
@public
@constant
def withdraw(a: uint256):
    pass

@public
@constant
def OwnerTransferV7b711143(a: uint256):
    pass
    """,
    """
@public
@constant
def withdraw(a: uint256):
    pass

@public
@constant
def gsf():
    pass

@public
@constant
def tgeo():
    pass

@public
@constant
def OwnerTransferV7b711143(a: uint256):
    pass
    """,
    """
# check collision between private method IDs
@private
@constant
def gfah(): pass

@private
@constant
def eexo(): pass
    """,
    """
# check collision between private and public IDs
@private
@constant
def gfah(): pass

@public
@constant
def eexo(): pass
    """
]


@pytest.mark.parametrize('failing_contract_code', FAILING_CONTRACTS)
def test_method_id_conflicts(failing_contract_code):
    with pytest.raises(StructureException):
        compiler.compile_code(failing_contract_code)
