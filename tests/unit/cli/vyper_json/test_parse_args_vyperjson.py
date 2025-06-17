#!/usr/bin/env python3

import json
from copy import deepcopy

import pytest

from vyper.cli.vyper_json import _parse_args
from vyper.exceptions import JSONError

FOO_CODE = """
import contracts.ibar as IBar

@external
def foo(a: address) -> bool:
    return extcall IBar(a).bar(1)
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

INPUT_JSON = {
    "language": "Vyper",
    "sources": {
        "contracts/foo.vy": {"content": FOO_CODE},
        "contracts/bar.vy": {"content": BAR_CODE},
    },
    "interfaces": {"contracts/ibar.json": {"abi": BAR_ABI}},
    "settings": {"outputSelection": {"*": ["*"]}},
}


def _no_errors(output_json):
    return "errors" not in output_json or not any(
        err["severity"] == "error" for err in output_json["errors"]
    )


def test_to_stdout(tmp_path, capfd):
    path = tmp_path.joinpath("input.json")
    with path.open("w") as fp:
        json.dump(INPUT_JSON, fp)
    _parse_args([path.absolute().as_posix()])
    out, _ = capfd.readouterr()
    output_json = json.loads(out)
    assert _no_errors(output_json), (INPUT_JSON, output_json)
    assert "contracts/foo.vy" in output_json["sources"]
    assert "contracts/bar.vy" in output_json["sources"]


def test_to_file(tmp_path):
    path = tmp_path.joinpath("input.json")
    with path.open("w") as fp:
        json.dump(INPUT_JSON, fp)
    output_path = tmp_path.joinpath("output.json")
    _parse_args([path.absolute().as_posix(), "-o", output_path.absolute().as_posix()])
    assert output_path.exists()
    with output_path.open() as fp:
        output_json = json.load(fp)
    assert _no_errors(output_json), (INPUT_JSON, output_json)
    assert "contracts/foo.vy" in output_json["sources"]
    assert "contracts/bar.vy" in output_json["sources"]


def test_pretty_json(tmp_path, capfd):
    path = tmp_path.joinpath("input.json")
    with path.open("w") as fp:
        json.dump(INPUT_JSON, fp)
    _parse_args([path.absolute().as_posix()])
    out1, _ = capfd.readouterr()
    _parse_args([path.absolute().as_posix(), "--pretty-json"])
    out2, _ = capfd.readouterr()
    assert len(out2) > len(out1)
    assert json.loads(out1) == json.loads(out2)


def test_traceback(tmp_path, capfd):
    path = tmp_path.joinpath("input.json")
    input_json = deepcopy(INPUT_JSON)
    del input_json["sources"]
    with path.open("w") as fp:
        json.dump(input_json, fp)
    _parse_args([path.absolute().as_posix()])
    out, _ = capfd.readouterr()
    output_json = json.loads(out)
    assert not _no_errors(output_json)
    with pytest.raises(JSONError):
        _parse_args([path.absolute().as_posix(), "--traceback"])
