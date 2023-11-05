#!/usr/bin/env python3

import vyper
from vyper.cli.vyper_json import compile_json
from vyper.compiler import OUTPUT_FORMATS, compile_code

FOO_CODE = """
@external
def foo() -> bool:
    return True
"""


INPUT_JSON = {
    "language": "Vyper",
    "sources": {"foo.vy": {"content": FOO_CODE}},
    "settings": {"outputSelection": {"*": ["*"]}},
}


def test_keys():
    data = compile_code(FOO_CODE, contract_name="foo.vy", output_formats=OUTPUT_FORMATS)
    output_json = compile_json(INPUT_JSON)
    assert sorted(output_json.keys()) == ["compiler", "contracts", "sources"]
    assert output_json["compiler"] == f"vyper-{vyper.__version__}"
    assert output_json["sources"]["foo.vy"] == {"id": 0, "ast": data["ast_dict"]["ast"]}
    assert output_json["contracts"]["foo.vy"]["foo"] == {
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
