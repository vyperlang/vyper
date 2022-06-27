#!/usr/bin/env python3
import argparse
import json
import sys
import warnings
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, Iterator, Set, TypeVar

import vyper
from vyper.interpreter.stmt import interpret_module


def _parse_cli_args():
    return _parse_args(sys.argv[1:])


def _parse_args(argv):
    contract_path = argv[1]

def exc_handler(contract_path: ContractPath, exception: Exception) -> None:
    print(f"Error compiling: {contract_path}")
    raise exception


def get_interface_codes(root_path: Path, contract_sources: ContractCodes) -> Dict:
    interface_codes: Dict = {}
    interfaces: Dict = {}

    for file_path, code in contract_sources.items():
        interfaces[file_path] = {}
        parent_path = root_path.joinpath(file_path).parent

        interface_codes = extract_file_interface_imports(code)
        for interface_name, interface_path in interface_codes.items():

            base_paths = [parent_path]
            if not interface_path.startswith(".") and root_path.joinpath(file_path).exists():
                base_paths.append(root_path)
            elif interface_path.startswith("../") and len(Path(file_path).parent.parts) < Path(
                interface_path
            ).parts.count(".."):
                raise FileNotFoundError(
                    f"{file_path} - Cannot perform relative import outside of base folder"
                )

            valid_path = get_interface_file_path(base_paths, interface_path)
            with valid_path.open() as fh:
                code = fh.read()
                if valid_path.suffix == ".json":
                    contents = json.loads(code.encode())

                    # EthPM Manifest (EIP-2678)
                    if "contractTypes" in contents:
                        if (
                            interface_name not in contents["contractTypes"]
                            or "abi" not in contents["contractTypes"][interface_name]
                        ):
                            raise ValueError(
                                f"Could not find interface '{interface_name}'"
                                f" in manifest '{valid_path}'."
                            )

                        interfaces[file_path][interface_name] = {
                            "type": "json",
                            "code": contents["contractTypes"][interface_name]["abi"],
                        }

                    # ABI JSON file (either `List[ABI]` or `{"abi": List[ABI]}`)
                    elif isinstance(contents, list) or (
                        "abi" in contents and isinstance(contents["abi"], list)
                    ):
                        interfaces[file_path][interface_name] = {"type": "json", "code": contents}

                    else:
                        raise ValueError(f"Corrupted file: '{valid_path}'")

                else:
                    interfaces[file_path][interface_name] = {"type": "vyper", "code": code}

    return interfaces


def interpret(
    input_files: Iterable[str],
    output_formats: OutputFormats,
    root_folder: str = ".",
    show_gas_estimates: bool = False,
    evm_version: str = DEFAULT_EVM_VERSION,
    no_optimize: bool = False,
    storage_layout: Iterable[str] = None,
) -> OrderedDict:

    root_path = Path(root_folder).resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Invalid root path - '{root_path.as_posix()}' does not exist")

    contract_sources: ContractCodes = OrderedDict()
    for file_name in input_files:
        file_path = Path(file_name)
        try:
            file_str = file_path.resolve().relative_to(root_path).as_posix()
        except ValueError:
            file_str = file_path.as_posix()
        with file_path.open() as fh:
            # trailing newline fixes python parsing bug when source ends in a comment
            # https://bugs.python.org/issue35107
            contract_sources[file_str] = fh.read() + "\n"

    storage_layouts = OrderedDict()
    if storage_layout:
        for storage_file_name, contract_name in zip(storage_layout, contract_sources.keys()):
            storage_file_path = Path(storage_file_name)
            with storage_file_path.open() as sfh:
                storage_layouts[contract_name] = json.load(sfh)

    show_version = False
    if "combined_json" in output_formats:
        if len(output_formats) > 1:
            raise ValueError("If using combined_json it must be the only output format requested")
        output_formats = combined_json_outputs
        show_version = True

    translate_map = {"abi_python": "abi", "json": "abi", "ast": "ast_dict", "ir_json": "ir_dict"}
    final_formats = [translate_map.get(i, i) for i in output_formats]

    compiler_data = vyper.compile_codes(
        contract_sources,
        final_formats,
        exc_handler=exc_handler,
        interface_codes=get_interface_codes(root_path, contract_sources),
        evm_version=evm_version,
        no_optimize=no_optimize,
        storage_layouts=storage_layouts,
        show_gas_estimates=show_gas_estimates,
    )
    if show_version:
        compiler_data["version"] = vyper.__version__

    return compiler_data


if __name__ == "__main__":
    _parse_args(sys.argv[1:])
