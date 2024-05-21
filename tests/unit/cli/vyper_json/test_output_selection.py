from pathlib import PurePath

import pytest

from vyper.cli.vyper_json import TRANSLATE_MAP, get_output_formats
from vyper.exceptions import JSONError


def test_no_outputs():
    with pytest.raises(KeyError):
        get_output_formats({})


def test_invalid_output():
    input_json = {
        "sources": {"foo.vy": ""},
        "settings": {"outputSelection": {"foo.vy": ["abi", "foobar"]}},
    }
    with pytest.raises(JSONError):
        get_output_formats(input_json)


def test_unknown_contract():
    input_json = {"sources": {}, "settings": {"outputSelection": {"bar.vy": ["abi"]}}}
    with pytest.raises(JSONError):
        get_output_formats(input_json)


@pytest.mark.parametrize("output", TRANSLATE_MAP.items())
def test_translate_map(output):
    input_json = {
        "sources": {"foo.vy": ""},
        "settings": {"outputSelection": {"foo.vy": [output[0]]}},
    }
    assert get_output_formats(input_json) == {PurePath("foo.vy"): [output[1]]}


def test_star():
    input_json = {
        "sources": {"foo.vy": "", "bar.vy": ""},
        "settings": {"outputSelection": {"*": ["*"]}},
    }
    expected = sorted(set(TRANSLATE_MAP.values()))
    result = get_output_formats(input_json)
    assert result == {PurePath("foo.vy"): expected, PurePath("bar.vy"): expected}


def test_ast():
    input_json = {
        "sources": {"foo.vy": ""},
        "settings": {"outputSelection": {"foo.vy": ["ast", "annotated_ast"]}},
    }
    expected = sorted([TRANSLATE_MAP[k] for k in ["ast", "annotated_ast"]])
    result = get_output_formats(input_json)
    assert result == {PurePath("foo.vy"): expected}


def test_evm():
    input_json = {
        "sources": {"foo.vy": ""},
        "settings": {"outputSelection": {"foo.vy": ["abi", "evm"]}},
    }
    expected = ["abi"] + sorted(v for k, v in TRANSLATE_MAP.items() if k.startswith("evm"))
    result = get_output_formats(input_json)
    assert result == {PurePath("foo.vy"): expected}


def test_solc_style():
    input_json = {
        "sources": {"foo.vy": ""},
        "settings": {"outputSelection": {"foo.vy": {"": ["abi"], "foo.vy": ["ir"]}}},
    }
    assert get_output_formats(input_json) == {PurePath("foo.vy"): ["abi", "ir_dict"]}


def test_metadata():
    input_json = {"sources": {"foo.vy": ""}, "settings": {"outputSelection": {"*": ["metadata"]}}}
    assert get_output_formats(input_json) == {PurePath("foo.vy"): ["metadata"]}
