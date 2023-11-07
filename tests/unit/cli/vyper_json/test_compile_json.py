import json

import pytest

import vyper
from vyper.cli.vyper_json import compile_from_input_dict, compile_json, exc_handler_to_dict
from vyper.compiler import OUTPUT_FORMATS, compile_code
from vyper.exceptions import InvalidType, JSONError, SyntaxException

FOO_CODE = """
import contracts.bar as Bar

@external
def foo(a: address) -> bool:
    return Bar(a).bar(1)

@external
def baz() -> uint256:
    return self.balance
"""

BAR_CODE = """
@external
def bar(a: uint256) -> bool:
    return True
"""

BAD_SYNTAX_CODE = """
def bar()>:
"""

BAD_COMPILER_CODE = """
@external
def oopsie(a: uint256) -> bool:
    return 42
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


@pytest.fixture(scope="function")
def input_json():
    return {
        "language": "Vyper",
        "sources": {
            "contracts/foo.vy": {"content": FOO_CODE},
            "contracts/bar.vy": {"content": BAR_CODE},
        },
        "interfaces": {"contracts/ibar.json": {"abi": BAR_ABI}},
        "settings": {"outputSelection": {"*": ["*"]}},
    }


# test string and dict inputs both work
def test_string_input(input_json):
    assert compile_json(input_json) == compile_json(json.dumps(input_json))


def test_bad_json():
    with pytest.raises(JSONError):
        compile_json("this probably isn't valid JSON, is it")


def test_keyerror_becomes_jsonerror(input_json):
    del input_json["sources"]
    with pytest.raises(KeyError):
        compile_from_input_dict(input_json)
    with pytest.raises(JSONError):
        compile_json(input_json)


def test_compile_json(input_json, make_input_bundle):
    input_bundle = make_input_bundle({"contracts/bar.vy": BAR_CODE})

    foo = compile_code(
        FOO_CODE,
        source_id=0,
        contract_name="contracts/foo.vy",
        output_formats=OUTPUT_FORMATS,
        input_bundle=input_bundle,
    )
    bar = compile_code(
        BAR_CODE, source_id=1, contract_name="contracts/bar.vy", output_formats=OUTPUT_FORMATS
    )

    compile_code_results = {"contracts/bar.vy": bar, "contracts/foo.vy": foo}

    output_json = compile_json(input_json)
    assert list(output_json["contracts"].keys()) == ["contracts/foo.vy", "contracts/bar.vy"]

    assert sorted(output_json.keys()) == ["compiler", "contracts", "sources"]
    assert output_json["compiler"] == f"vyper-{vyper.__version__}"

    for source_id, contract_name in enumerate(["foo", "bar"]):
        path = f"contracts/{contract_name}.vy"
        data = compile_code_results[path]
        assert output_json["sources"][path] == {"id": source_id, "ast": data["ast_dict"]["ast"]}
        assert output_json["contracts"][path][contract_name] == {
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


def test_different_outputs(make_input_bundle, input_json):
    input_json["settings"]["outputSelection"] = {
        "contracts/bar.vy": "*",
        "contracts/foo.vy": ["evm.methodIdentifiers"],
    }
    output_json = compile_json(input_json)
    assert list(output_json["contracts"].keys()) == ["contracts/foo.vy", "contracts/bar.vy"]

    assert sorted(output_json.keys()) == ["compiler", "contracts", "sources"]
    assert output_json["compiler"] == f"vyper-{vyper.__version__}"

    contracts = output_json["contracts"]

    foo = contracts["contracts/foo.vy"]["foo"]
    bar = contracts["contracts/bar.vy"]["bar"]
    assert sorted(bar.keys()) == ["abi", "devdoc", "evm", "interface", "ir", "metadata", "userdoc"]

    assert sorted(foo.keys()) == ["evm"]

    # check method_identifiers
    input_bundle = make_input_bundle({"contracts/bar.vy": BAR_CODE})
    method_identifiers = compile_code(
        FOO_CODE,
        contract_name="contracts/foo.vy",
        output_formats=["method_identifiers"],
        input_bundle=input_bundle,
    )["method_identifiers"]
    assert foo["evm"]["methodIdentifiers"] == method_identifiers


def test_root_folder_not_exists(input_json):
    with pytest.raises(FileNotFoundError):
        compile_json(input_json, root_folder="/path/that/does/not/exist")


def test_wrong_language():
    with pytest.raises(JSONError):
        compile_json({"language": "Solidity"})


def test_exc_handler_raises_syntax(input_json):
    input_json["sources"]["badcode.vy"] = {"content": BAD_SYNTAX_CODE}
    with pytest.raises(SyntaxException):
        compile_json(input_json)


def test_exc_handler_to_dict_syntax(input_json):
    input_json["sources"]["badcode.vy"] = {"content": BAD_SYNTAX_CODE}
    result = compile_json(input_json, exc_handler_to_dict)
    assert "errors" in result
    assert len(result["errors"]) == 1
    error = result["errors"][0]
    assert error["component"] == "compiler", error
    assert error["type"] == "SyntaxException"


def test_exc_handler_raises_compiler(input_json):
    input_json["sources"]["badcode.vy"] = {"content": BAD_COMPILER_CODE}
    with pytest.raises(InvalidType):
        compile_json(input_json)


def test_exc_handler_to_dict_compiler(input_json):
    input_json["sources"]["badcode.vy"] = {"content": BAD_COMPILER_CODE}
    result = compile_json(input_json, exc_handler_to_dict)
    assert sorted(result.keys()) == ["compiler", "errors"]
    assert result["compiler"] == f"vyper-{vyper.__version__}"
    assert len(result["errors"]) == 1
    error = result["errors"][0]
    assert error["component"] == "compiler"
    assert error["type"] == "InvalidType"


def test_source_ids_increment(input_json):
    input_json["settings"]["outputSelection"] = {"*": ["evm.deployedBytecode.sourceMap"]}
    result = compile_json(input_json)

    def get(filename, contractname):
        return result["contracts"][filename][contractname]["evm"]["deployedBytecode"]["sourceMap"]

    assert get("contracts/foo.vy", "foo").startswith("-1:-1:0")
    assert get("contracts/bar.vy", "bar").startswith("-1:-1:1")


def test_relative_import_paths(input_json):
    input_json["sources"]["contracts/potato/baz/baz.vy"] = {"content": """from ... import foo"""}
    input_json["sources"]["contracts/potato/baz/potato.vy"] = {"content": """from . import baz"""}
    input_json["sources"]["contracts/potato/footato.vy"] = {"content": """from baz import baz"""}
    compile_from_input_dict(input_json)
