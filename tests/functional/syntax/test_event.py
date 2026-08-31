import json

import pytest

from vyper.compiler import compile_code, compile_from_file_input
from vyper.exceptions import EventDeclarationException, StructureException, TypeMismatch


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


def test_json_abi_indexed_non_value_type_rejected(make_input_bundle):
    abi = json.dumps(
        [
            {
                "type": "event",
                "name": "E",
                "anonymous": False,
                "inputs": [{"name": "a", "type": "uint256[3]", "indexed": True}],
            }
        ]
    )
    main = """
import iface
    """
    input_bundle = make_input_bundle({"iface.json": abi, "main.vy": main})
    file_input = input_bundle.load_file("main.vy")

    with pytest.raises(TypeMismatch) as e:
        compile_from_file_input(file_input, input_bundle=input_bundle)
    assert "Event indexes may only be value types" in str(e.value)


def test_json_abi_anonymous_four_indexed_accepted(make_input_bundle):
    abi = json.dumps(
        [
            {
                "type": "event",
                "name": "E",
                "anonymous": True,
                "inputs": [
                    {"name": "a", "type": "uint256", "indexed": True},
                    {"name": "b", "type": "uint256", "indexed": True},
                    {"name": "c", "type": "uint256", "indexed": True},
                    {"name": "d", "type": "uint256", "indexed": True},
                ],
            }
        ]
    )
    main = """
import iface
    """
    input_bundle = make_input_bundle({"iface.json": abi, "main.vy": main})
    file_input = input_bundle.load_file("main.vy")

    assert compile_from_file_input(file_input, input_bundle=input_bundle) is not None


def test_json_abi_more_than_three_indexed_rejected(make_input_bundle):
    abi = json.dumps(
        [
            {
                "type": "event",
                "name": "E",
                "anonymous": False,
                "inputs": [
                    {"name": "a", "type": "uint256", "indexed": True},
                    {"name": "b", "type": "uint256", "indexed": True},
                    {"name": "c", "type": "uint256", "indexed": True},
                    {"name": "d", "type": "uint256", "indexed": True},
                ],
            }
        ]
    )
    main = """
import iface
    """
    input_bundle = make_input_bundle({"iface.json": abi, "main.vy": main})
    file_input = input_bundle.load_file("main.vy")

    with pytest.raises(EventDeclarationException) as e:
        compile_from_file_input(file_input, input_bundle=input_bundle)
    assert "Event cannot have more than three indexed arguments" in str(e.value)


def test_json_abi_anonymous_more_than_four_indexed_rejected(make_input_bundle):
    abi = json.dumps(
        [
            {
                "type": "event",
                "name": "E",
                "anonymous": True,
                "inputs": [
                    {"name": "a", "type": "uint256", "indexed": True},
                    {"name": "b", "type": "uint256", "indexed": True},
                    {"name": "c", "type": "uint256", "indexed": True},
                    {"name": "d", "type": "uint256", "indexed": True},
                    {"name": "e", "type": "uint256", "indexed": True},
                ],
            }
        ]
    )
    main = """
import iface
    """
    input_bundle = make_input_bundle({"iface.json": abi, "main.vy": main})
    file_input = input_bundle.load_file("main.vy")

    with pytest.raises(EventDeclarationException) as e:
        compile_from_file_input(file_input, input_bundle=input_bundle)
    assert "Anonymous event cannot have more than four indexed arguments" in str(e.value)
