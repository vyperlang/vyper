#!/usr/bin/env python3

import pytest

from vyper.cli.vyper_json import get_input_dict_interfaces, get_interface_codes
from vyper.exceptions import JSONError

FOO_CODE = """
import contracts.bar as Bar

@external
def foo(a: address) -> bool:
    return Bar(a).bar(1)
"""

BAR_CODE = """
@external
def bar(a: uint256) -> bool:
    return True
"""

BAR_ABI = [
    {
        "name": "bar",
        "outputs": [{"type": "bool", "name": "out"}],
        "inputs": [{"type": "uint256", "name": "a"}],
        "stateMutability": "nonpayable",
        "type": "function",
        "gas": 313,
    }
]


# get_input_dict_interfaces tests


def test_no_interfaces():
    result = get_input_dict_interfaces({})
    assert isinstance(result, dict)
    assert not result


def test_interface_collision():
    input_json = {"interfaces": {"bar.json": {"abi": BAR_ABI}, "bar.vy": {"content": BAR_CODE}}}
    with pytest.raises(JSONError):
        get_input_dict_interfaces(input_json)


def test_interfaces_wrong_suffix():
    input_json = {"interfaces": {"foo.abi": {"content": FOO_CODE}}}
    with pytest.raises(JSONError):
        get_input_dict_interfaces(input_json)

    input_json = {"interfaces": {"interface.folder/foo": {"content": FOO_CODE}}}
    with pytest.raises(JSONError):
        get_input_dict_interfaces(input_json)


def test_json_no_abi():
    input_json = {"interfaces": {"bar.json": {"content": BAR_ABI}}}
    with pytest.raises(JSONError):
        get_input_dict_interfaces(input_json)


def test_vy_no_content():
    input_json = {"interfaces": {"bar.vy": {"abi": BAR_CODE}}}
    with pytest.raises(JSONError):
        get_input_dict_interfaces(input_json)


def test_interfaces_output():
    input_json = {
        "interfaces": {
            "bar.json": {"abi": BAR_ABI},
            "interface.folder/bar2.vy": {"content": BAR_CODE},
        }
    }
    result = get_input_dict_interfaces(input_json)
    assert isinstance(result, dict)
    assert result == {
        "bar": {"type": "json", "code": BAR_ABI},
        "interface.folder/bar2": {"type": "vyper", "code": BAR_CODE},
    }


def test_manifest_output():
    input_json = {"interfaces": {"bar.json": {"contractTypes": {"Bar": {"abi": BAR_ABI}}}}}
    result = get_input_dict_interfaces(input_json)
    assert isinstance(result, dict)
    assert result == {"Bar": {"type": "json", "code": BAR_ABI}}


# get_interface_codes tests


def test_interface_codes_from_contracts():
    # interface should be generated from contract
    assert get_interface_codes(
        None, "foo.vy", {"foo.vy": FOO_CODE, "contracts/bar.vy": BAR_CODE}, {}
    )
    assert get_interface_codes(
        None, "foo/foo.vy", {"foo/foo.vy": FOO_CODE, "contracts/bar.vy": BAR_CODE}, {}
    )


def test_interface_codes_from_interfaces():
    # existing interface should be given preference over contract-as-interface
    contracts = {"foo.vy": FOO_CODE, "contacts/bar.vy": BAR_CODE}
    result = get_interface_codes(None, "foo.vy", contracts, {"contracts/bar": "bar"})
    assert result["Bar"] == "bar"


def test_root_path(tmp_path):
    tmp_path.joinpath("contracts").mkdir()
    with tmp_path.joinpath("contracts/bar.vy").open("w") as fp:
        fp.write("bar")

    with pytest.raises(FileNotFoundError):
        get_interface_codes(None, "foo.vy", {"foo.vy": FOO_CODE}, {})

    # interface from file system should take lowest priority
    result = get_interface_codes(tmp_path, "foo.vy", {"foo.vy": FOO_CODE}, {})
    assert result["Bar"] == {"code": "bar", "type": "vyper"}
    contracts = {"foo.vy": FOO_CODE, "contracts/bar.vy": BAR_CODE}
    result = get_interface_codes(None, "foo.vy", contracts, {})
    assert result["Bar"] == {"code": BAR_CODE, "type": "vyper"}
