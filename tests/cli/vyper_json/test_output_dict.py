#!/usr/bin/env python3

import vyper
from vyper.cli.vyper_json import format_to_output_dict
from vyper.compiler import OUTPUT_FORMATS, compile_codes

FOO_CODE = """
@external
def foo() -> bool:
    breakpoint()
    y: uint256 = 3
    x: uint256 = y + 1
    breakpoint()
    return True
"""


def test_keys():
    compiler_data = compile_codes({"foo.vy": FOO_CODE}, output_formats=list(OUTPUT_FORMATS.keys()))
    output_json = format_to_output_dict(compiler_data)
    assert sorted(output_json.keys()) == ["compiler", "contracts", "sources"]
    assert output_json["compiler"] == f"vyper-{vyper.__version__}"
    data = compiler_data["foo.vy"]
    assert output_json["sources"]["foo.vy"] == {"id": 0, "ast": data["ast_dict"]["ast"]}
    assert data["breakpoints"] == [5, 8]
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
                "breakpoints": data["breakpoints"],
                "pcBreakpoints": data["pc_breakpoints"],
                "sourceMap": data["source_map"]["pc_pos_map_compressed"],
                "errorMap": data["error_map"],
            },
            "methodIdentifiers": data["method_identifiers"],
        },
    }
