#!/usr/bin/env python3
import argparse
import json
import sys
import warnings
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, Iterator, Set, TypeVar

import vyper
import vyper.codegen.ir_node as ir_node
from vyper.cli import vyper_json
from vyper.cli.utils import extract_file_interface_imports, get_interface_file_path
from vyper.compiler.settings import VYPER_TRACEBACK_LIMIT
from vyper.evm.opcodes import DEFAULT_EVM_VERSION, EVM_VERSIONS
from vyper.typing import ContractCodes, ContractPath, OutputFormats

T = TypeVar("T")

format_options_help = """Format to print, one or more of:
bytecode (default) - Deployable bytecode
bytecode_runtime   - Bytecode at runtime
blueprint_bytecode - Deployment bytecode for an ERC-5202 compatible blueprint
abi                - ABI in JSON format
abi_python         - ABI in python format
source_map         - Vyper source map
method_identifiers - Dictionary of method signature to method identifier
userdoc            - Natspec user documentation
devdoc             - Natspec developer documentation
combined_json      - All of the above format options combined as single JSON output
layout             - Storage layout of a Vyper contract
ast                - AST in JSON format
interface          - Vyper interface of a contract
external_interface - External interface of a contract, used for outside contract calls
opcodes            - List of opcodes as a string
opcodes_runtime    - List of runtime opcodes as a string
ir                 - Intermediate representation in list format
ir_json            - Intermediate representation in JSON format
hex-ir             - Output IR and assembly constants in hex instead of decimal
no-optimize        - Do not optimize (don't use this for production code)
no-bytecode-metadata - Do not add metadata to bytecode
"""

combined_json_outputs = [
    "bytecode",
    "bytecode_runtime",
    "blueprint_bytecode",
    "abi",
    "layout",
    "source_map",
    "method_identifiers",
    "userdoc",
    "devdoc",
]


def _parse_cli_args():
    return _parse_args(sys.argv[1:])


def _cli_helper(f, output_formats, compiled):
    if output_formats == ("combined_json",):
        print(json.dumps(compiled), file=f)
        return

    for contract_data in compiled.values():
        for data in contract_data.values():
            if isinstance(data, (list, dict)):
                print(json.dumps(data), file=f)
            else:
                print(data, file=f)


def _parse_args(argv):
    warnings.simplefilter("always")

    if "--standard-json" in argv:
        argv.remove("--standard-json")
        vyper_json._parse_args(argv)
        return

    parser = argparse.ArgumentParser(
        description="Pythonic Smart Contract Language for the EVM",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("input_files", help="Vyper sourcecode to compile", nargs="+")
    parser.add_argument(
        "--version", action="version", version=f"{vyper.__version__}+commit.{vyper.__commit__}"
    )
    parser.add_argument(
        "--show-gas-estimates",
        help="Show gas estimates in abi and ir output mode.",
        action="store_true",
    )
    parser.add_argument("-f", help=format_options_help, default="bytecode", dest="format")
    parser.add_argument(
        "--storage-layout-file",
        help="Override storage slots provided by compiler",
        dest="storage_layout",
        nargs="+",
    )
    parser.add_argument(
        "--evm-version",
        help=f"Select desired EVM version (default {DEFAULT_EVM_VERSION}). "
        " note: cancun support is EXPERIMENTAL",
        choices=list(EVM_VERSIONS),
        default=DEFAULT_EVM_VERSION,
        dest="evm_version",
    )
    parser.add_argument("--no-optimize", help="Do not optimize", action="store_true")
    parser.add_argument(
        "--no-bytecode-metadata", help="Do not add metadata to bytecode", action="store_true"
    )
    parser.add_argument(
        "--traceback-limit",
        help="Set the traceback limit for error messages reported by the compiler",
        type=int,
    )
    parser.add_argument(
        "--verbose",
        help="Turn on compiler verbose output. "
        "Currently an alias for --traceback-limit but "
        "may add more information in the future",
        action="store_true",
    )
    parser.add_argument(
        "--standard-json",
        help="Switch to standard JSON mode. Use `--standard-json -h` for available options.",
        action="store_true",
    )
    parser.add_argument("--hex-ir", action="store_true")
    parser.add_argument(
        "-p", help="Set the root path for contract imports", default=".", dest="root_folder"
    )
    parser.add_argument("-o", help="Set the output path", dest="output_path")

    args = parser.parse_args(argv)

    if args.traceback_limit is not None:
        sys.tracebacklimit = args.traceback_limit
    elif VYPER_TRACEBACK_LIMIT is not None:
        sys.tracebacklimit = VYPER_TRACEBACK_LIMIT
    elif args.verbose:
        sys.tracebacklimit = 1000
    else:
        # Python usually defaults sys.tracebacklimit to 1000.  We use a default
        # setting of zero so error printouts only include information about where
        # an error occurred in a Vyper source file.
        sys.tracebacklimit = 0

    if args.hex_ir:
        ir_node.AS_HEX_DEFAULT = True

    output_formats = tuple(uniq(args.format.split(",")))

    compiled = compile_files(
        args.input_files,
        output_formats,
        args.root_folder,
        args.show_gas_estimates,
        args.evm_version,
        args.no_optimize,
        args.storage_layout,
        args.no_bytecode_metadata,
    )

    if args.output_path:
        with open(args.output_path, "w") as f:
            _cli_helper(f, output_formats, compiled)
    else:
        f = sys.stdout
        _cli_helper(f, output_formats, compiled)


def uniq(seq: Iterable[T]) -> Iterator[T]:
    """
    Yield unique items in ``seq`` in order.
    """
    seen: Set[T] = set()

    for x in seq:
        if x in seen:
            continue

        seen.add(x)
        yield x


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


def compile_files(
    input_files: Iterable[str],
    output_formats: OutputFormats,
    root_folder: str = ".",
    show_gas_estimates: bool = False,
    evm_version: str = DEFAULT_EVM_VERSION,
    no_optimize: bool = False,
    storage_layout: Iterable[str] = None,
    no_bytecode_metadata: bool = False,
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
        no_bytecode_metadata=no_bytecode_metadata,
    )
    if show_version:
        compiler_data["version"] = vyper.__version__

    return compiler_data


if __name__ == "__main__":
    _parse_args(sys.argv[1:])
