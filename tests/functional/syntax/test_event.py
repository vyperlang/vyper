import pytest

from vyper.compiler import compile_code
from vyper.exceptions import StructureException


def test_event_with_module_as_member_errors(make_input_bundle):
    top = """
import x
event E:
    f: x
        """
    x = ""

    input_bundle = make_input_bundle({"top.vy": top, "x.vy": x})

    with pytest.raises(StructureException) as e:
        compile_code(top, input_bundle=input_bundle)

    assert "not a valid event member" in str(e.value)


def test_event_with_address_member():
    code = """
event E:
    address: uint256

@external
def foo():
    log E(address=1)
    """
    assert compile_code(code) is not None


def test_event_with_address_name_and_type():
    code = """
event E:
    address: address

@external
def foo():
    log E(address=msg.sender)
    """
    assert compile_code(code) is not None
