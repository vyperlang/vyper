from pathlib import PurePath

import pytest

from vyper.cli.vyper_json import get_inputs
from vyper.exceptions import JSONError
from vyper.utils import keccak256

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


def test_no_sources():
    with pytest.raises(KeyError):
        get_inputs({})


def test_contracts_urls():
    with pytest.raises(JSONError):
        get_inputs({"sources": {"foo.vy": {"urls": ["https://foo.code.com/"]}}})


def test_contracts_no_content_key():
    with pytest.raises(JSONError):
        get_inputs({"sources": {"foo.vy": FOO_CODE}})


def test_contracts_keccak():
    hash_ = keccak256(FOO_CODE.encode()).hex()

    input_json = {"sources": {"foo.vy": {"content": FOO_CODE, "keccak256": hash_}}}
    get_inputs(input_json)

    input_json["sources"]["foo.vy"]["keccak256"] = "0x" + hash_
    get_inputs(input_json)

    input_json["sources"]["foo.vy"]["keccak256"] = "0x1234567890"
    with pytest.raises(JSONError):
        get_inputs(input_json)


def test_contracts_outside_pwd():
    input_json = {"sources": {"../foo.vy": {"content": FOO_CODE}}}
    get_inputs(input_json)


def test_contract_collision():
    # ./foo.vy and foo.vy will resolve to the same path
    input_json = {"sources": {"./foo.vy": {"content": FOO_CODE}, "foo.vy": {"content": FOO_CODE}}}
    with pytest.raises(JSONError):
        get_inputs(input_json)


def test_contracts_return_value():
    input_json = {
        "sources": {"foo.vy": {"content": FOO_CODE}, "contracts/bar.vy": {"content": BAR_CODE}}
    }
    result = get_inputs(input_json)
    assert result == {
        PurePath("foo.vy"): {"content": FOO_CODE},
        PurePath("contracts/bar.vy"): {"content": BAR_CODE},
    }


BAR_ABI = [
    {
        "name": "bar",
        "outputs": [{"type": "bool", "name": "out"}],
        "inputs": [{"type": "uint256", "name": "a"}],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


# tests to get interfaces from input dicts


def test_interface_collision():
    input_json = {
        "sources": {"foo.vy": {"content": FOO_CODE}},
        "interfaces": {"bar.json": {"abi": BAR_ABI}, "bar.vy": {"content": BAR_CODE}},
    }
    with pytest.raises(JSONError):
        get_inputs(input_json)


def test_json_no_abi():
    input_json = {
        "sources": {"foo.vy": {"content": FOO_CODE}},
        "interfaces": {"bar.json": {"content": BAR_ABI}},
    }
    with pytest.raises(JSONError):
        get_inputs(input_json)


def test_vy_no_content():
    input_json = {
        "sources": {"foo.vy": {"content": FOO_CODE}},
        "interfaces": {"bar.vy": {"abi": BAR_CODE}},
    }
    with pytest.raises(JSONError):
        get_inputs(input_json)


def test_interfaces_output():
    input_json = {
        "sources": {"foo.vy": {"content": FOO_CODE}},
        "interfaces": {
            "bar.json": {"abi": BAR_ABI},
            "interface.folder/bar2.vy": {"content": BAR_CODE},
        },
    }
    result = get_inputs(input_json)
    assert result == {
        PurePath("foo.vy"): {"content": FOO_CODE},
        PurePath("bar.json"): {"abi": BAR_ABI},
        PurePath("interface.folder/bar2.vy"): {"content": BAR_CODE},
    }


# EIP-2678 -- not currently supported
@pytest.mark.xfail
def test_manifest_output():
    input_json = {"interfaces": {"bar.json": {"contractTypes": {"Bar": {"abi": BAR_ABI}}}}}
    result = get_inputs(input_json)
    assert isinstance(result, dict)
    assert result == {"Bar": {"type": "json", "code": BAR_ABI}}
