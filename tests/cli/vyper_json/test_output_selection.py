#!/usr/bin/env python3

import pytest

from vyper.cli.vyper_json import TRANSLATE_MAP, get_input_dict_output_formats
from vyper.exceptions import JSONError


def test_no_outputs():
    with pytest.raises(KeyError):
        get_input_dict_output_formats({}, {})


def test_invalid_output():
    input_json = {"settings": {"outputSelection": {"foo.vy": ["abi", "foobar"]}}}
    sources = {"foo.vy": ""}
    with pytest.raises(JSONError):
        get_input_dict_output_formats(input_json, sources)


def test_unknown_contract():
    input_json = {"settings": {"outputSelection": {"bar.vy": ["abi"]}}}
    sources = {"foo.vy": ""}
    with pytest.raises(JSONError):
        get_input_dict_output_formats(input_json, sources)


@pytest.mark.parametrize("output", TRANSLATE_MAP.items())
def test_translate_map(output):
    input_json = {"settings": {"outputSelection": {"foo.vy": [output[0]]}}}
    sources = {"foo.vy": ""}
    assert get_input_dict_output_formats(input_json, sources) == {"foo.vy": [output[1]]}


def test_star():
    input_json = {"settings": {"outputSelection": {"*": ["*"]}}}
    sources = {"foo.vy": "", "bar.vy": ""}
    expected = sorted(set(TRANSLATE_MAP.values()))
    result = get_input_dict_output_formats(input_json, sources)
    assert result == {"foo.vy": expected, "bar.vy": expected}


def test_evm():
    input_json = {"settings": {"outputSelection": {"foo.vy": ["abi", "evm"]}}}
    sources = {"foo.vy": ""}
    expected = ["abi"] + sorted(v for k, v in TRANSLATE_MAP.items() if k.startswith("evm"))
    result = get_input_dict_output_formats(input_json, sources)
    assert result == {"foo.vy": expected}


def test_solc_style():
    input_json = {"settings": {"outputSelection": {"foo.vy": {"": ["abi"], "foo.vy": ["ir"]}}}}
    sources = {"foo.vy": ""}
    assert get_input_dict_output_formats(input_json, sources) == {"foo.vy": ["abi", "ir_dict"]}
