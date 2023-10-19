import pytest

from vyper import compiler
from vyper.exceptions import StructureException

FAILING_CONTRACTS = [
    """
@external
@view
def gsf():
    pass

@external
@view
def tgeo():
    pass
    """,
    """
@external
@view
def withdraw(a: uint256):
    pass

@external
@view
def OwnerTransferV7b711143(a: uint256):
    pass
    """,
    """
@external
@view
def withdraw(a: uint256):
    pass

@external
@view
def gsf():
    pass

@external
@view
def tgeo():
    pass

@external
@view
def OwnerTransferV7b711143(a: uint256):
    pass
    """,
    """
# check collision with ID = 0x00000000
wycpnbqcyf:public(uint256)

@external
def randallsRevenge_ilxaotc(): pass
    """,
]


@pytest.mark.parametrize("failing_contract_code", FAILING_CONTRACTS)
def test_method_id_conflicts(failing_contract_code):
    with pytest.raises(StructureException):
        compiler.compile_code(failing_contract_code)
