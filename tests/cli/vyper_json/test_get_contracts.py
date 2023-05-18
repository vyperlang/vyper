#!/usr/bin/env python3

import pytest

from vyper.cli.vyper_json import get_input_dict_contracts
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
        get_input_dict_contracts({})


def test_contracts_urls():
    with pytest.raises(JSONError):
        get_input_dict_contracts({"sources": {"foo.vy": {"urls": ["https://foo.code.com/"]}}})


def test_contracts_no_content_key():
    with pytest.raises(JSONError):
        get_input_dict_contracts({"sources": {"foo.vy": FOO_CODE}})


def test_contracts_keccak():
    hash_ = keccak256(FOO_CODE.encode()).hex()

    input_json = {"sources": {"foo.vy": {"content": FOO_CODE, "keccak256": hash_}}}
    get_input_dict_contracts(input_json)

    input_json["sources"]["foo.vy"]["keccak256"] = "0x" + hash_
    get_input_dict_contracts(input_json)

    input_json["sources"]["foo.vy"]["keccak256"] = "0x1234567890"
    with pytest.raises(JSONError):
        get_input_dict_contracts(input_json)


def test_contracts_bad_path():
    input_json = {"sources": {"../foo.vy": {"content": FOO_CODE}}}
    with pytest.raises(JSONError):
        get_input_dict_contracts(input_json)


def test_contract_collision():
    # ./foo.vy and foo.vy will resolve to the same path
    input_json = {"sources": {"./foo.vy": {"content": FOO_CODE}, "foo.vy": {"content": FOO_CODE}}}
    with pytest.raises(JSONError):
        get_input_dict_contracts(input_json)


def test_contracts_return_value():
    input_json = {
        "sources": {"foo.vy": {"content": FOO_CODE}, "contracts/bar.vy": {"content": BAR_CODE}}
    }
    result = get_input_dict_contracts(input_json)
    assert result == {"foo.vy": FOO_CODE, "contracts/bar.vy": BAR_CODE}
