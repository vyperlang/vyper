#!/usr/bin/env python3

import pytest

from vyper.cli.vyper_json import get_compilation_targets
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
    }
]


# tests to get interfaces from input dicts


def test_interface_collision():
    input_json = {"sources": {"foo.vy": {"content": FOO_CODE}}, "interfaces": {"bar.json": {"abi": BAR_ABI}, "bar.vy": {"content": BAR_CODE}}}
    with pytest.raises(JSONError):
        get_compilation_targets(input_json)


def test_json_no_abi():
    input_json = {"sources": {"foo.vy": {"content": FOO_CODE}}, "interfaces": {"bar.json": {"content": BAR_ABI}}}
    with pytest.raises(JSONError):
        get_compilation_targets(input_json)


def test_vy_no_content():
    input_json = {"sources": {"foo.vy": {"content": FOO_CODE}}, "interfaces": {"bar.vy": {"abi": BAR_CODE}}}
    with pytest.raises(JSONError):
        get_compilation_targets(input_json)


def test_interfaces_output():
    input_json = {
        "sources": {"foo.vy": {"content": FOO_CODE}},
        "interfaces": {
            "bar.json": {"abi": BAR_ABI},
            "interface.folder/bar2.vy": {"content": BAR_CODE},
        }
    }
    result = get_compilation_targets(input_json)
    assert isinstance(result, dict)
    assert result == {
        "bar": {"type": "json", "code": BAR_ABI},
        "interface.folder/bar2": {"type": "vyper", "code": BAR_CODE},
    }


# EIP-2678 -- not currently supported
@pytest.mark.xfail
def test_manifest_output():
    input_json = {"interfaces": {"bar.json": {"contractTypes": {"Bar": {"abi": BAR_ABI}}}}}
    result = get_compilation_targets(input_json)
    assert isinstance(result, dict)
    assert result == {"Bar": {"type": "json", "code": BAR_ABI}}
