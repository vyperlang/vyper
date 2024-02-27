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
    with pytest.raises(StructureException) as e:
        compiler.compile_code(failing_contract_code)

    assert e.value._message.startswith("Methods produce colliding method ID")


export_fails = [
    {
        "lib1.vy": """
wycpnbqcyf:public(uint256)
        """,
        "MAIN": """
import lib1

initializes: lib1
exports: lib1.wycpnbqcyf

@external
def randallsRevenge_ilxaotc(): pass
    """,
    },
    {
        "lib1.vy": """
@external
@view
def withdraw(a: uint256):
    pass

@external
@view
def gsf():
    pass
    """,
        "MAIN": """
import lib1

exports: (lib1.gsf, lib1.withdraw)

@external
@view
def tgeo():
    pass

@external
@view
def OwnerTransferV7b711143(a: uint256):
    pass
    """,
    },
]


@pytest.mark.parametrize("files", export_fails)
def test_method_id_conflicts_export(files, make_input_bundle):
    main = files.pop("MAIN")
    input_bundle = make_input_bundle(files)
    with pytest.raises(StructureException) as e:
        compiler.compile_code(main, input_bundle=input_bundle)

    assert e.value._message.startswith("Methods produce colliding method ID")
