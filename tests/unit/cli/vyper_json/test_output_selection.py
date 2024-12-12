from pathlib import PurePath

import pytest

from vyper import compiler
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


def test_metadata_contain_all_reachable_functions(make_input_bundle):
    code_a = """
@internal
def foo() -> uint256:
    return 43

@internal
def faa() -> uint256:
    return 76
        """

    code_b = """
import A

@internal
def foo() -> uint256:
    return 43

@external
def bar():
    self.foo()
    A.foo()
    assert 1 != 12
        """

    input_bundle = make_input_bundle({"A.vy": code_a, "B.vy": code_b})

    out = compiler.compile_code(code_b, input_bundle=input_bundle, output_formats=["metadata"])[
        "metadata"
    ]["function_info"]

    def has_suffix_key(data: dict, suffix: str) -> bool:
        for key in data.keys():
            if key.endswith(suffix):
                return True
        return False

    assert has_suffix_key(out, "foo (0)")
    assert has_suffix_key(out, "bar")
    assert has_suffix_key(out, "foo (1)")
    assert not has_suffix_key(out, "faa")
