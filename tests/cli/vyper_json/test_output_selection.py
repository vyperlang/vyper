from pathlib import PurePath

import pytest

from vyper.cli.vyper_json import TRANSLATE_MAP, get_output_formats
from vyper.exceptions import JSONError


def test_no_outputs():
    with pytest.raises(KeyError):
        get_output_formats({}, {})


def test_invalid_output():
    input_json = {"settings": {"outputSelection": {"foo.vy": ["abi", "foobar"]}}}
    targets = [PurePath("foo.vy")]
    with pytest.raises(JSONError):
        get_output_formats(input_json, targets)


def test_unknown_contract():
    input_json = {"settings": {"outputSelection": {"bar.vy": ["abi"]}}}
    targets = [PurePath("foo.vy")]
    with pytest.raises(JSONError):
        get_output_formats(input_json, targets)


@pytest.mark.parametrize("output", TRANSLATE_MAP.items())
def test_translate_map(output):
    input_json = {"settings": {"outputSelection": {"foo.vy": [output[0]]}}}
    targets = [PurePath("foo.vy")]
    assert get_output_formats(input_json, targets) == {PurePath("foo.vy"): [output[1]]}


def test_star():
    input_json = {"settings": {"outputSelection": {"*": ["*"]}}}
    targets = [PurePath("foo.vy"), PurePath("bar.vy")]
    expected = sorted(set(TRANSLATE_MAP.values()))
    result = get_output_formats(input_json, targets)
    assert result == {PurePath("foo.vy"): expected, PurePath("bar.vy"): expected}


def test_evm():
    input_json = {"settings": {"outputSelection": {"foo.vy": ["abi", "evm"]}}}
    targets = [PurePath("foo.vy")]
    expected = ["abi"] + sorted(v for k, v in TRANSLATE_MAP.items() if k.startswith("evm"))
    result = get_output_formats(input_json, targets)
    assert result == {PurePath("foo.vy"): expected}


def test_solc_style():
    input_json = {"settings": {"outputSelection": {"foo.vy": {"": ["abi"], "foo.vy": ["ir"]}}}}
    targets = [PurePath("foo.vy")]
    assert get_output_formats(input_json, targets) == {PurePath("foo.vy"): ["abi", "ir_dict"]}


def test_metadata():
    input_json = {"settings": {"outputSelection": {"*": ["metadata"]}}}
    targets = [PurePath("foo.vy")]
    assert get_output_formats(input_json, targets) == {PurePath("foo.vy"): ["metadata"]}
