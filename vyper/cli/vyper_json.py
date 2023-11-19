#!/usr/bin/env python3

import argparse
import json
import sys
import warnings
from pathlib import Path, PurePath
from typing import Any, Callable, Hashable, Optional

import vyper
from vyper.compiler.input_bundle import FileInput, JSONInputBundle
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.evm.opcodes import EVM_VERSIONS
from vyper.exceptions import JSONError
from vyper.utils import keccak256

TRANSLATE_MAP = {
    "abi": "abi",
    "ast": "ast_dict",
    "devdoc": "devdoc",
    "evm.methodIdentifiers": "method_identifiers",
    "evm.bytecode.object": "bytecode",
    "evm.bytecode.opcodes": "opcodes",
    "evm.deployedBytecode.object": "bytecode_runtime",
    "evm.deployedBytecode.opcodes": "opcodes_runtime",
    "evm.deployedBytecode.sourceMap": "source_map",
    "evm.deployedBytecode.sourceMapFull": "source_map_full",
    "interface": "interface",
    "ir": "ir_dict",
    "ir_runtime": "ir_runtime_dict",
    "metadata": "metadata",
    "layout": "layout",
    "userdoc": "userdoc",
}


def _parse_cli_args():
    return _parse_args(sys.argv[1:])


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Vyper programming language for EVM - JSON Compiler",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "input_file",
        help="JSON file to compile from. If none is given, Vyper will receive it from stdin.",
        nargs="?",
    )
    parser.add_argument(
        "--version", action="version", version=f"{vyper.__version__}+commit.{vyper.__commit__}"
    )
    parser.add_argument(
        "-o",
        help="Filename to save JSON output to. If the file exists it will be overwritten.",
        default=None,
        dest="output_file",
    )
    parser.add_argument(
        "-p",
        help="Set a base import path. Vyper searches here if a file is not found in the JSON.",
        default=None,
        dest="root_folder",
    )
    parser.add_argument("--pretty-json", help="Output JSON in pretty format.", action="store_true")
    parser.add_argument(
        "--traceback",
        help="Show python traceback on error instead of returning JSON",
        action="store_true",
    )

    args = parser.parse_args(argv)
    if args.input_file:
        with Path(args.input_file).open() as fh:
            input_json = fh.read()
        json_path = Path(args.input_file).resolve().as_posix()
    else:
        input_json = "".join(sys.stdin.read()).strip()
        json_path = "<stdin>"

    exc_handler = exc_handler_raises if args.traceback else exc_handler_to_dict
    output_json = json.dumps(
        compile_json(input_json, exc_handler, args.root_folder, json_path),
        indent=2 if args.pretty_json else None,
        sort_keys=True,
        default=str,
    )

    if args.output_file is not None:
        output_path = Path(args.output_file).resolve()
        with output_path.open("w") as fh:
            fh.write(output_json)
        print(f"Results saved to {output_path}")
    else:
        print(output_json)


def exc_handler_raises(file_path: Optional[str], exception: Exception, component: str) -> None:
    if file_path:
        print(f"Unhandled exception in '{file_path}':")
    exception._exc_handler = True  # type: ignore
    raise exception


def exc_handler_to_dict(file_path: Optional[str], exception: Exception, component: str) -> dict:
    err_dict: dict = {
        "type": type(exception).__name__,
        "component": component,
        "severity": "error",
        "message": str(exception).strip('"'),
    }
    if hasattr(exception, "message"):
        err_dict.update(
            {"message": exception.message, "formattedMessage": str(exception)}  # type: ignore
        )
    if file_path is not None:
        err_dict["sourceLocation"] = {"file": file_path}
        if getattr(exception, "lineno", None) is not None:
            err_dict["sourceLocation"].update(
                {
                    "lineno": exception.lineno,  # type: ignore
                    "col_offset": getattr(exception, "col_offset", None),
                }
            )

    output_json = {"compiler": f"vyper-{vyper.__version__}", "errors": [err_dict]}
    return output_json


def get_evm_version(input_dict: dict) -> Optional[str]:
    if "settings" not in input_dict:
        return None

    # TODO: move this validation somewhere it can be reused more easily
    evm_version = input_dict["settings"].get("evmVersion")
    if evm_version is None:
        return None

    if evm_version in (
        "homestead",
        "tangerineWhistle",
        "spuriousDragon",
        "byzantium",
        "constantinople",
    ):
        raise JSONError("Vyper does not support pre-istanbul EVM versions")
    if evm_version not in EVM_VERSIONS:
        raise JSONError(f"Unknown EVM version - '{evm_version}'")

    return evm_version


def get_compilation_targets(input_dict: dict) -> list[PurePath]:
    # TODO: once we have modules, add optional "compilation_targets" key
    # which specifies which sources we actually want to compile.

    return [PurePath(p) for p in input_dict["sources"].keys()]


def get_inputs(input_dict: dict) -> dict[PurePath, Any]:
    ret = {}
    seen = {}

    for path, value in input_dict["sources"].items():
        path = PurePath(path)
        if "urls" in value:
            raise JSONError(f"{path} - 'urls' is not a supported field, use 'content' instead")
        if "content" not in value:
            raise JSONError(f"{path} missing required field - 'content'")
        if "keccak256" in value:
            hash_ = value["keccak256"].lower().removeprefix("0x")
            if hash_ != keccak256(value["content"].encode("utf-8")).hex():
                raise JSONError(
                    f"Calculated keccak of '{path}' does not match keccak given in input JSON"
                )
        if path.stem in seen:
            raise JSONError(f"Contract namespace collision: {path}")

        # value looks like {"content": <source code>}
        # this will be interpreted by JSONInputBundle later
        ret[path] = value
        seen[path.stem] = True

    for path, value in input_dict.get("interfaces", {}).items():
        path = PurePath(path)
        if path.stem in seen:
            raise JSONError(f"Interface namespace collision: {path}")

        if isinstance(value, list):
            # backwards compatibility - straight ABI with no "abi" key.
            # (should probably just reject these)
            value = {"abi": value}

        # some validation
        if not isinstance(value, dict):
            raise JSONError("invalid interface (must be a dictionary):\n{json.dumps(value)}")
        if "content" in value:
            if not isinstance(value["content"], str):
                raise JSONError(f"invalid 'content' (expected string):\n{json.dumps(value)}")
        elif "abi" in value:
            if not isinstance(value["abi"], list):
                raise JSONError(f"invalid 'abi' (expected list):\n{json.dumps(value)}")
        else:
            raise JSONError(
                "invalid interface (must contain either 'content' or 'abi'):\n{json.dumps(value)}"
            )
        if "content" in value and "abi" in value:
            raise JSONError(
                "invalid interface (found both 'content' and 'abi'):\n{json.dumps(value)}"
            )

        ret[path] = value
        seen[path.stem] = True

    return ret


# get unique output formats for each contract, given the input_dict
# NOTE: would maybe be nice to raise on duplicated output formats
def get_output_formats(input_dict: dict, targets: list[PurePath]) -> dict[PurePath, list[str]]:
    output_formats: dict[PurePath, list[str]] = {}
    for path, outputs in input_dict["settings"]["outputSelection"].items():
        if isinstance(outputs, dict):
            # if outputs are given in solc json format, collapse them into a single list
            outputs = set(x for i in outputs.values() for x in i)
        else:
            outputs = set(outputs)

        for key in [i for i in ("evm", "evm.bytecode", "evm.deployedBytecode") if i in outputs]:
            outputs.remove(key)
            outputs.update([i for i in TRANSLATE_MAP if i.startswith(key)])

        if "*" in outputs:
            outputs = TRANSLATE_MAP.values()
        else:
            try:
                outputs = [TRANSLATE_MAP[i] for i in outputs]
            except KeyError as e:
                raise JSONError(f"Invalid outputSelection - {e}")

        outputs = sorted(set(outputs))

        if path == "*":
            output_paths = targets
        else:
            output_paths = [PurePath(path)]
            if output_paths[0] not in targets:
                raise JSONError(f"outputSelection references unknown contract '{output_paths[0]}'")

        for output_path in output_paths:
            output_formats[output_path] = outputs

    return output_formats


def compile_from_input_dict(
    input_dict: dict, exc_handler: Callable = exc_handler_raises, root_folder: Optional[str] = None
) -> tuple[dict, dict]:
    if root_folder is None:
        root_folder = "."

    if input_dict["language"] != "Vyper":
        raise JSONError(f"Invalid language '{input_dict['language']}' - Only Vyper is supported.")

    evm_version = get_evm_version(input_dict)

    optimize = input_dict["settings"].get("optimize")
    if isinstance(optimize, bool):
        # bool optimization level for backwards compatibility
        warnings.warn(
            "optimize: <bool> is deprecated! please use one of 'gas', 'codesize', 'none'."
        )
        optimize = OptimizationLevel.default() if optimize else OptimizationLevel.NONE
    elif isinstance(optimize, str):
        optimize = OptimizationLevel.from_string(optimize)
    else:
        assert optimize is None

    settings = Settings(evm_version=evm_version, optimize=optimize)

    no_bytecode_metadata = not input_dict["settings"].get("bytecodeMetadata", True)

    compilation_targets = get_compilation_targets(input_dict)
    sources = get_inputs(input_dict)
    output_formats = get_output_formats(input_dict, compilation_targets)

    input_bundle = JSONInputBundle(sources, search_paths=[Path(root_folder)])

    res, warnings_dict = {}, {}
    warnings.simplefilter("always")
    for contract_path in compilation_targets:
        with warnings.catch_warnings(record=True) as caught_warnings:
            try:
                # use load_file to get a unique source_id
                file = input_bundle.load_file(contract_path)
                assert isinstance(file, FileInput)  # mypy hint
                data = vyper.compile_code(
                    file.source_code,
                    contract_name=str(file.path),
                    input_bundle=input_bundle,
                    output_formats=output_formats[contract_path],
                    source_id=file.source_id,
                    settings=settings,
                    no_bytecode_metadata=no_bytecode_metadata,
                )
                assert isinstance(data, dict)
                data["source_id"] = file.source_id
            except Exception as exc:
                return exc_handler(contract_path, exc, "compiler"), {}
            res[contract_path] = data
            if caught_warnings:
                warnings_dict[contract_path] = caught_warnings

    return res, warnings_dict


# convert output of compile_input_dict to final output format
def format_to_output_dict(compiler_data: dict) -> dict:
    output_dict: dict = {"compiler": f"vyper-{vyper.__version__}", "contracts": {}, "sources": {}}
    for path, data in compiler_data.items():
        path = str(path)  # Path breaks json serializability
        output_dict["sources"][path] = {"id": data["source_id"]}
        if "ast_dict" in data:
            output_dict["sources"][path]["ast"] = data["ast_dict"]["ast"]

        name = PurePath(path).stem
        output_dict["contracts"][path] = {name: {}}
        output_contracts = output_dict["contracts"][path][name]

        if "ir_dict" in data:
            output_contracts["ir"] = data["ir_dict"]

        for key in ("abi", "devdoc", "interface", "metadata", "userdoc"):
            if key in data:
                output_contracts[key] = data[key]

        if "method_identifiers" in data:
            output_contracts["evm"] = {"methodIdentifiers": data["method_identifiers"]}

        evm_keys = ("bytecode", "opcodes")
        if any(i in data for i in evm_keys):
            evm = output_contracts.setdefault("evm", {}).setdefault("bytecode", {})
            if "bytecode" in data:
                evm["object"] = data["bytecode"]
            if "opcodes" in data:
                evm["opcodes"] = data["opcodes"]

        pc_maps_keys = ("source_map", "source_map_full")
        if any(i + "_runtime" in data for i in evm_keys) or any(i in data for i in pc_maps_keys):
            evm = output_contracts.setdefault("evm", {}).setdefault("deployedBytecode", {})
            if "bytecode_runtime" in data:
                evm["object"] = data["bytecode_runtime"]
            if "opcodes_runtime" in data:
                evm["opcodes"] = data["opcodes_runtime"]
            if "source_map" in data:
                evm["sourceMap"] = data["source_map"]["pc_pos_map_compressed"]
            if "source_map_full" in data:
                evm["sourceMapFull"] = data["source_map_full"]

    return output_dict


# https://stackoverflow.com/a/49518779
def _raise_on_duplicate_keys(ordered_pairs: list[tuple[Hashable, Any]]) -> dict:
    """
    Raise JSONError if a duplicate key exists in provided ordered list
    of pairs, otherwise return a dict.
    """
    dict_out = {}
    for key, val in ordered_pairs:
        if key in dict_out:
            raise JSONError(f"Duplicate key: {key}")
        else:
            dict_out[key] = val
    return dict_out


def compile_json(
    input_json: dict | str,
    exc_handler: Callable = exc_handler_raises,
    root_folder: Optional[str] = None,
    json_path: Optional[str] = None,
) -> dict:
    try:
        if isinstance(input_json, str):
            try:
                input_dict = json.loads(input_json, object_pairs_hook=_raise_on_duplicate_keys)
            except json.decoder.JSONDecodeError as exc:
                new_exc = JSONError(str(exc), exc.lineno, exc.colno)
                return exc_handler(json_path, new_exc, "json")
        else:
            input_dict = input_json

        try:
            compiler_data, warn_data = compile_from_input_dict(input_dict, exc_handler, root_folder)
            if "errors" in compiler_data:
                return compiler_data
        except KeyError as exc:
            new_exc = JSONError(f"Input JSON missing required field: {str(exc)}")
            return exc_handler(json_path, new_exc, "json")
        except (FileNotFoundError, JSONError) as exc:
            return exc_handler(json_path, exc, "json")

        output_dict = format_to_output_dict(compiler_data)
        if warn_data:
            output_dict["errors"] = []
            for path, msg in ((k, x) for k, v in warn_data.items() for x in v):
                output_dict["errors"].append(
                    {
                        "type": msg.category.__name__,
                        "component": "compiler",
                        "severity": "warning",
                        "message": msg.message,
                        "sourceLocation": {"file": path},
                    }
                )
        return output_dict

    except Exception as exc:
        if hasattr(exc, "_exc_handler"):
            # exception was already handled by exc_handler_raises
            raise
        exc.lineno = sys.exc_info()[-1].tb_lineno  # type: ignore
        file_path = sys.exc_info()[-1].tb_frame.f_code.co_filename  # type: ignore
        return exc_handler(file_path, exc, "vyper")
