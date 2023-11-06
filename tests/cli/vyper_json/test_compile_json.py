import json
from copy import deepcopy

import pytest

import vyper
from vyper.compiler import compile_code, OUTPUT_FORMATS
from vyper.cli.vyper_json import compile_from_input_dict, compile_json
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

INPUT_JSON = {
    "language": "Vyper",
    "sources": {
        "contracts/foo.vy": {"content": FOO_CODE},
        "contracts/bar.vy": {"content": BAR_CODE},
    },
    "interfaces": {"contracts/ibar.json": {"abi": BAR_ABI}},
    "settings": {"outputSelection": {"*": ["*"]}},
}


def test_input_formats():
    assert compile_json(INPUT_JSON) == compile_json(json.dumps(INPUT_JSON))


def test_bad_json():
    with pytest.raises(JSONError):
        compile_json("this probably isn't valid JSON, is it")


def test_keyerror_becomes_jsonerror():
    input_json = deepcopy(INPUT_JSON)
    del input_json["sources"]
    with pytest.raises(KeyError):
        compile_from_input_dict(input_json)
    with pytest.raises(JSONError):
        compile_json(input_json)

def test_keys():
    data = compile_code(BAR_CODE, contract_name="bar.vy", output_formats=OUTPUT_FORMATS)
    input_json = {
        "language": "Vyper",
        "sources": {
            "bar.vy": {"content": BAR_CODE},
        },
        "settings": {"outputSelection": {"*": ["*"]}},
    }
    output_json = compile_json(input_json)


    assert sorted(output_json.keys()) == ["compiler", "contracts", "sources"]
    assert output_json["compiler"] == f"vyper-{vyper.__version__}"
    assert output_json["sources"]["bar.vy"] == {"id": 0, "ast": data["ast_dict"]["ast"]}
    assert output_json["contracts"]["bar.vy"]["bar"] == {
        "abi": data["abi"],
        "devdoc": data["devdoc"],
        "interface": data["interface"],
        "ir": data["ir_dict"],
        "userdoc": data["userdoc"],
        "metadata": data["metadata"],
        "evm": {
            "bytecode": {"object": data["bytecode"], "opcodes": data["opcodes"]},
            "deployedBytecode": {
                "object": data["bytecode_runtime"],
                "opcodes": data["opcodes_runtime"],
                "sourceMap": data["source_map"]["pc_pos_map_compressed"],
                "sourceMapFull": data["source_map_full"],
            },
            "methodIdentifiers": data["method_identifiers"],
        },
    }
