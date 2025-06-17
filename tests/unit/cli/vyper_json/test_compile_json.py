import json
from pathlib import PurePath

import pytest

import vyper
from vyper.cli.vyper_json import (
    VENOM_KEYS,
    compile_from_input_dict,
    compile_json,
    exc_handler_to_dict,
    get_inputs,
    get_settings,
)
from vyper.compiler import OUTPUT_FORMATS, compile_code, compile_from_file_input
from vyper.compiler.input_bundle import JSONInput, JSONInputBundle
from vyper.exceptions import JSONError, SyntaxException, TypeMismatch

FOO_CODE = """
import contracts.ibar as IBar

import contracts.library as library

a: uint256
b: uint256

@external
def foo(a: address) -> bool:
    return extcall IBar(a).bar(1)

@external
def baz() -> uint256:
    return self.balance + library.foo()
"""

FOO_STORAGE_LAYOUT_OVERRIDES = {
    "a": {"type": "uint256", "n_slots": 1, "slot": 5},
    "b": {"type": "uint256", "n_slots": 1, "slot": 0},
}

BAR_CODE = """
import contracts.ibar as IBar

implements: IBar

c: uint256
d: uint256

@external
def bar(a: uint256) -> bool:
    return True
"""

BAR_STORAGE_LAYOUT_OVERRIDES = {
    "c": {"type": "uint256", "n_slots": 1, "slot": 13},
    "d": {"type": "uint256", "n_slots": 1, "slot": 7},
}

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
def input_json(optimize, evm_version, experimental_codegen, debug):
    return {
        "language": "Vyper",
        "sources": {
            "contracts/foo.vy": {"content": FOO_CODE},
            "contracts/library.vy": {"content": LIBRARY_CODE},
            "contracts/bar.vy": {"content": BAR_CODE},
        },
        "interfaces": {"contracts/ibar.json": {"abi": BAR_ABI}},
        "settings": {
            "outputSelection": {"*": ["*"]},
            "optimize": optimize.name.lower(),
            "evmVersion": evm_version,
            "experimentalCodegen": experimental_codegen,
            "debug": debug,
        },
        "storage_layout_overrides": {
            "contracts/foo.vy": {"foo_overrides.json": FOO_STORAGE_LAYOUT_OVERRIDES},
            "contracts/bar.vy": {"bar_overrides.json": BAR_STORAGE_LAYOUT_OVERRIDES},
        },
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


def json_input(json_data, path):
    path = PurePath(path)
    return JSONInput(
        contents=json.dumps(json_data), data=json_data, source_id=-1, path=path, resolved_path=path
    )


def test_compile_json(input_json, input_bundle, experimental_codegen):
    foo_input = input_bundle.load_file("contracts/foo.vy")
    # remove venom related from output formats
    # because they require venom (experimental)
    output_formats = OUTPUT_FORMATS.copy()
    foo = compile_from_file_input(
        foo_input,
        output_formats=output_formats,
        input_bundle=input_bundle,
        storage_layout_override=json_input(FOO_STORAGE_LAYOUT_OVERRIDES, path="foo_override.json"),
    )

    library_input = input_bundle.load_file("contracts/library.vy")
    library = compile_from_file_input(
        library_input, output_formats=output_formats, input_bundle=input_bundle
    )

    bar_input = input_bundle.load_file("contracts/bar.vy")
    bar = compile_from_file_input(
        bar_input,
        output_formats=output_formats,
        input_bundle=input_bundle,
        storage_layout_override=json_input(BAR_STORAGE_LAYOUT_OVERRIDES, path="bar_override.json"),
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
        expected = {
            "abi": data["abi"],
            "devdoc": data["devdoc"],
            "interface": data["interface"],
            "ir": data["ir_dict"],
            "userdoc": data["userdoc"],
            "layout": data["layout"],
            "metadata": data["metadata"],
            "evm": {
                "bytecode": {
                    "object": data["bytecode"],
                    "opcodes": data["opcodes"],
                    "sourceMap": data["source_map"],
                },
                "deployedBytecode": {
                    "object": data["bytecode_runtime"],
                    "opcodes": data["opcodes_runtime"],
                    "sourceMap": data["source_map_runtime"],
                },
                "methodIdentifiers": data["method_identifiers"],
            },
        }
        if experimental_codegen:
            expected["venom"] = {
                "bb": repr(data["bb"]),
                "bb_runtime": repr(data["bb_runtime"]),
                "cfg": data["cfg"],
                "cfg_runtime": data["cfg_runtime"],
            }
        assert output_json["contracts"][path][contract_name] == expected


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


def test_different_outputs(input_bundle, input_json, experimental_codegen):
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
    expected_keys = ["abi", "devdoc", "evm", "interface", "ir", "layout", "metadata", "userdoc"]
    if experimental_codegen:
        expected_keys.append("venom")
        expected_keys.sort()
    assert sorted(bar.keys()) == expected_keys

    assert sorted(foo.keys()) == ["evm"]

    # check method_identifiers
    method_identifiers = compile_code(
        FOO_CODE,
        contract_path="contracts/foo.vy",
        output_formats=["method_identifiers"],
        input_bundle=input_bundle,
    )["method_identifiers"]
    assert foo["evm"]["methodIdentifiers"] == method_identifiers


def test_wrong_language():
    with pytest.raises(JSONError):
        compile_json({"language": "Solidity"})


def test_exc_handler_raises_syntax(input_json):
    input_json["sources"]["badcode.vy"] = {"content": BAD_SYNTAX_CODE}
    with pytest.raises(SyntaxException, match=r'contract "badcode\.vy:\d+"'):
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


def test_unknown_storage_layout_overrides(input_json):
    unknown_contract_path = "contracts/baz.vy"
    input_json["storage_layout_overrides"] = {
        unknown_contract_path: {"foo_override.json": FOO_STORAGE_LAYOUT_OVERRIDES}
    }
    with pytest.raises(JSONError) as e:
        compile_json(input_json)
    assert e.value.args[0] == f"unknown target for storage layout override: {unknown_contract_path}"


def test_source_ids_increment(input_json):
    input_json["settings"]["outputSelection"] = {"*": ["ast", "evm.deployedBytecode.sourceMap"]}
    result = compile_json(input_json)

    def get(filename, contractname):
        ast = result["sources"][filename]["ast"]
        ret = ast["source_id"]

        # grab it via source map to sanity check
        contract_info = result["contracts"][filename][contractname]["evm"]
        pc_ast_map = contract_info["deployedBytecode"]["sourceMap"]["pc_ast_map"]
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
    input_json["sources"]["contracts/potato/footato.vy"] = {"content": "from .baz import baz"}
    compile_from_input_dict(input_json)


def test_compile_json_with_abi_top(make_input_bundle):
    stream = """
{
  "abi": [
    {
      "name": "validate",
      "inputs": [
        { "name": "creator", "type": "address" },
        { "name": "token", "type": "address" },
        { "name": "amount_per_second", "type": "uint256" },
        { "name": "reason", "type": "bytes" }
      ],
      "outputs": [{ "name": "max_stream_life", "type": "uint256" }]
    }
  ]
}
    """
    code = """
from . import stream
    """
    input_bundle = make_input_bundle({"stream.json": stream, "code.vy": code})
    file_input = input_bundle.load_file("code.vy")
    vyper.compiler.compile_from_file_input(file_input, input_bundle=input_bundle)


def test_compile_json_with_experimental_codegen():
    code = {
        "language": "Vyper",
        "sources": {"foo.vy": {"content": "@external\ndef foo() -> bool:\n    return True"}},
        "settings": {
            "evmVersion": "cancun",
            "optimize": "gas",
            "venomExperimental": True,
            "search_paths": ["."],
            "outputSelection": {"*": VENOM_KEYS},
        },
    }
    compiled = compile_from_input_dict(code)
    expected = compiled[0][PurePath("foo.vy")]

    settings = get_settings(code)
    assert settings.experimental_codegen is True
    output_json = compile_json(code)
    assert "venom" in output_json["contracts"]["foo.vy"]["foo"]
    venom = output_json["contracts"]["foo.vy"]["foo"]["venom"]
    assert venom["bb"] == repr(expected["bb"])
    assert venom["bb_runtime"] == repr(expected["bb_runtime"])
    assert venom["cfg"] == expected["cfg"]
    assert venom["cfg_runtime"] == expected["cfg_runtime"]


def test_compile_json_subgraph_label():
    foo_code = """
a: uint256
b: address

@internal
def _foo(f: uint256, g: address) -> uint256:
    self.a = f
    self.b = g
    return self.a


@internal
def _bar(f: uint256, g: address) -> uint256:
    self._foo(f, g)
    self._foo(f, g)
    return self.a


@external
def call_foo(amount: uint256, account: address) -> uint256:
    return self._bar(amount, account)
    """
    code = {
        "language": "Vyper",
        "sources": {"foo.vy": {"content": foo_code}},
        "settings": {
            "evmVersion": "cancun",
            "optimize": "gas",
            "venomExperimental": True,
            "search_paths": ["."],
            "outputSelection": {"*": ["cfg_runtime"]},
        },
    }
    output_json = compile_json(code)
    venom = output_json["contracts"]["foo.vy"]["foo"]["venom"]
    # ensure that quotes are formatted properly in the output
    assert 'subgraph "internal 0 _foo(uint256,address)_runtime"' in venom["cfg_runtime"]


def test_compile_json_without_experimental_codegen():
    code = {
        "language": "Vyper",
        "sources": {"foo.vy": {"content": "@external\ndef foo() -> bool:\n    return True"}},
        "settings": {
            "evmVersion": "cancun",
            "optimize": "gas",
            "venomExperimental": False,
            "search_paths": ["."],
            "outputSelection": {"*": ["ast"]},
        },
    }

    settings = get_settings(code)
    assert settings.experimental_codegen is False
    output_json = compile_json(code)
    assert "venom" not in output_json["contracts"]["foo.vy"]["foo"]


def test_compile_json_with_both_venom_aliases():
    code = {
        "language": "Vyper",
        "sources": {"foo.vy": {"content": ""}},
        "settings": {
            "evmVersion": "cancun",
            "optimize": "gas",
            "experimentalCodegen": False,
            "venomExperimental": False,
            "search_paths": [],
            "outputSelection": {"*": ["ast"]},
        },
    }
    with pytest.raises(JSONError) as e:
        get_settings(code)
    assert e.value.args[0] == "both experimentalCodegen and venomExperimental cannot be set"
