import json
from pathlib import PurePath

import pytest

import vyper
from vyper.cli.vyper_json import (
    compile_from_input_dict,
    compile_json,
    exc_handler_to_dict,
    get_inputs,
)
from vyper.compiler import OUTPUT_FORMATS, compile_code, compile_from_file_input
from vyper.compiler.input_bundle import JSONInputBundle
from vyper.exceptions import JSONError, SyntaxException, TypeMismatch

FOO_CODE = """
import contracts.ibar as IBar

import contracts.library as library

@external
def foo(a: address) -> bool:
    return extcall IBar(a).bar(1)

@external
def baz() -> uint256:
    return self.balance + library.foo()
"""

BAR_CODE = """
import contracts.ibar as IBar

implements: IBar

@external
def bar(a: uint256) -> bool:
    return True
"""

BAR_VYI = """
@external
def bar(a: uint256) -> bool:
    ...
"""

LIBRARY_CODE = """
@internal
def foo() -> uint256:
    return block.number + 1
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
            "contracts/library.vy": {"content": LIBRARY_CODE},
            "contracts/bar.vy": {"content": BAR_CODE},
        },
        "interfaces": {"contracts/ibar.json": {"abi": BAR_ABI}},
        "settings": {"outputSelection": {"*": ["*"]}},
    }


@pytest.fixture(scope="function")
def input_bundle(input_json):
    # CMC 2023-12-11 maybe input_json -> JSONInputBundle should be a helper
    # function in `vyper_json.py`.
    sources = get_inputs(input_json)
    return JSONInputBundle(sources, search_paths=[PurePath(".")])


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


def test_compile_json(input_json, input_bundle):
    foo_input = input_bundle.load_file("contracts/foo.vy")
    # remove bb and bb_runtime from output formats
    # because they require venom (experimental)
    output_formats = OUTPUT_FORMATS.copy()
    del output_formats["bb"]
    del output_formats["bb_runtime"]
    foo = compile_from_file_input(
        foo_input, output_formats=output_formats, input_bundle=input_bundle
    )

    library_input = input_bundle.load_file("contracts/library.vy")
    library = compile_from_file_input(
        library_input, output_formats=output_formats, input_bundle=input_bundle
    )

    bar_input = input_bundle.load_file("contracts/bar.vy")
    bar = compile_from_file_input(
        bar_input, output_formats=output_formats, input_bundle=input_bundle
    )

    compile_code_results = {
        "contracts/bar.vy": bar,
        "contracts/library.vy": library,
        "contracts/foo.vy": foo,
    }

    output_json = compile_json(input_json)
    assert list(output_json["contracts"].keys()) == [
        "contracts/foo.vy",
        "contracts/library.vy",
        "contracts/bar.vy",
    ]

    assert sorted(output_json.keys()) == ["compiler", "contracts", "sources"]
    assert output_json["compiler"] == f"vyper-{vyper.__version__}"

    for source_id, contract_name in [(0, "foo"), (2, "library"), (3, "bar")]:
        path = f"contracts/{contract_name}.vy"
        data = compile_code_results[path]
        assert output_json["sources"][path] == {
            "id": source_id,
            "ast": data["ast_dict"]["ast"],
            "annotated_ast": data["annotated_ast_dict"]["ast"],
        }
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


def test_compilation_targets(input_json):
    output_json = compile_json(input_json)
    assert list(output_json["contracts"].keys()) == [
        "contracts/foo.vy",
        "contracts/library.vy",
        "contracts/bar.vy",
    ]

    # omit library.vy
    input_json["settings"]["outputSelection"] = {"contracts/foo.vy": "*", "contracts/bar.vy": "*"}
    output_json = compile_json(input_json)

    assert list(output_json["contracts"].keys()) == ["contracts/foo.vy", "contracts/bar.vy"]


def test_different_outputs(input_bundle, input_json):
    input_json["settings"]["outputSelection"] = {
        "contracts/bar.vy": "*",
        "contracts/foo.vy": ["evm.methodIdentifiers"],
    }
    output_json = compile_json(input_json)
    assert list(output_json["contracts"].keys()) == ["contracts/bar.vy", "contracts/foo.vy"]

    assert sorted(output_json.keys()) == ["compiler", "contracts", "sources"]
    assert output_json["compiler"] == f"vyper-{vyper.__version__}"

    contracts = output_json["contracts"]

    foo = contracts["contracts/foo.vy"]["foo"]
    bar = contracts["contracts/bar.vy"]["bar"]
    assert sorted(bar.keys()) == ["abi", "devdoc", "evm", "interface", "ir", "metadata", "userdoc"]

    assert sorted(foo.keys()) == ["evm"]

    # check method_identifiers
    method_identifiers = compile_code(
        FOO_CODE,
        contract_path="contracts/foo.vy",
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
    with pytest.raises(TypeMismatch):
        compile_json(input_json)


def test_exc_handler_to_dict_compiler(input_json):
    input_json["sources"]["badcode.vy"] = {"content": BAD_COMPILER_CODE}
    result = compile_json(input_json, exc_handler_to_dict)
    assert sorted(result.keys()) == ["compiler", "errors"]
    assert result["compiler"] == f"vyper-{vyper.__version__}"
    assert len(result["errors"]) == 1
    error = result["errors"][0]
    assert error["component"] == "compiler"
    assert error["type"] == "TypeMismatch"


def test_source_ids_increment(input_json):
    input_json["settings"]["outputSelection"] = {"*": ["ast", "evm.deployedBytecode.sourceMapFull"]}
    result = compile_json(input_json)

    def get(filename, contractname):
        ast = result["sources"][filename]["ast"]
        ret = ast["source_id"]

        # grab it via source map to sanity check
        contract_info = result["contracts"][filename][contractname]["evm"]
        pc_ast_map = contract_info["deployedBytecode"]["sourceMapFull"]["pc_ast_map"]
        pc_item = next(iter(pc_ast_map.values()))
        source_id, node_id = pc_item
        assert ret == source_id

        return ret

    assert get("contracts/foo.vy", "foo") == 0
    assert get("contracts/library.vy", "library") == 2
    assert get("contracts/bar.vy", "bar") == 3


def test_relative_import_paths(input_json):
    input_json["sources"]["contracts/potato/baz/baz.vy"] = {"content": "from ... import foo"}
    input_json["sources"]["contracts/potato/baz/potato.vy"] = {"content": "from . import baz"}
    input_json["sources"]["contracts/potato/footato.vy"] = {"content": "from baz import baz"}
    compile_from_input_dict(input_json)
