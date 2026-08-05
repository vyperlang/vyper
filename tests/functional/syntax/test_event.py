import pytest

from vyper.compiler import compile_code
from vyper.exceptions import StructureException, TypeMismatch


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


@pytest.mark.parametrize("bad_type", ["uint256[3]", "DynArray[uint256, 3]", "MyStruct"])
def test_indexed_non_value_type_rejected(bad_type):
    code = f"""
struct MyStruct:
    x: uint256

event E:
    a: indexed({bad_type})
    """
    with pytest.raises(TypeMismatch) as e:
        compile_code(code)
    assert "Event indexes may only be value types" in str(e.value)


@pytest.mark.parametrize(
    "good_type", ["uint256", "address", "bool", "bytes32", "Bytes[10]", "String[10]", "F"]
)
def test_indexed_value_types_accepted(good_type):
    code = f"""
flag F:
    A
    B

event E:
    a: indexed({good_type})
    """
    assert compile_code(code) is not None
