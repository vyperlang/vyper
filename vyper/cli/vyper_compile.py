#!/usr/bin/env python3
import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Set, TypeVar

import vyper
import vyper.codegen.ir_node as ir_node
from vyper.cli import vyper_json
from vyper.compiler.input_bundle import FileInput, FilesystemInputBundle
from vyper.compiler.settings import (
    VYPER_TRACEBACK_LIMIT,
    OptimizationLevel,
    Settings,
    _set_debug_mode,
)
from vyper.evm.opcodes import DEFAULT_EVM_VERSION, EVM_VERSIONS
from vyper.typing import ContractPath, OutputFormats

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
metadata           - Contract metadata (intended for use by tooling developers)
combined_json      - All of the above format options combined as single JSON output
layout             - Storage layout of a Vyper contract
ast                - AST (not yet annotated) in JSON format
annotated_ast      - Annotated AST in JSON format
interface          - Vyper interface of a contract
external_interface - External interface of a contract, used for outside contract calls
opcodes            - List of opcodes as a string
opcodes_runtime    - List of runtime opcodes as a string
ir                 - Intermediate representation in list format
ir_json            - Intermediate representation in JSON format
ir_runtime         - Intermediate representation of runtime bytecode in list format
asm                - Output the EVM assembly of the deployable bytecode
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
        "note: cancun support is EXPERIMENTAL",
        choices=list(EVM_VERSIONS),
        dest="evm_version",
    )
    parser.add_argument("--no-optimize", help="Do not optimize", action="store_true")
    parser.add_argument(
        "-O",
        "--optimize",
        help="Optimization flag (defaults to 'gas')",
        choices=["gas", "codesize", "none"],
    )
    parser.add_argument("--debug", help="Compile in debug mode", action="store_true")
    parser.add_argument(
        "--no-bytecode-metadata", help="Do not add metadata to bytecode", action="store_true"
    )
    parser.add_argument(
        "--traceback-limit",
        help="Set the traceback limit for error messages reported by the compiler",
        type=int,
    )
    parser.add_argument(
        "-v",
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
        "--path", "-p", help="Set the root path for contract imports", action="append", dest="paths"
    )
    parser.add_argument("-o", help="Set the output path", dest="output_path")
    parser.add_argument(
        "--experimental-codegen",
        help="The compiler use the new IR codegen. This is an experimental feature.",
        action="store_true",
        dest="experimental_codegen",
    )

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

    if args.debug:
        _set_debug_mode(True)

    if args.no_optimize and args.optimize:
        raise ValueError("Cannot use `--no-optimize` and `--optimize` at the same time!")

    settings = Settings()

    if args.no_optimize:
        settings.optimize = OptimizationLevel.NONE
    elif args.optimize is not None:
        settings.optimize = OptimizationLevel.from_string(args.optimize)

    if args.evm_version:
        settings.evm_version = args.evm_version

    if args.experimental_codegen:
        settings.experimental_codegen = args.experimental_codegen

    if args.verbose:
        print(f"cli specified: `{settings}`", file=sys.stderr)

    compiled = compile_files(
        args.input_files,
        output_formats,
        args.paths,
        args.show_gas_estimates,
        settings,
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


def get_search_paths(paths: list[str] = None) -> list[Path]:
    # given `paths` input, get the full search path, including
    # the system search path.
    paths = paths or []

    # lowest precedence search path is always sys path
    # note python sys path uses opposite resolution order from us
    # (first in list is highest precedence; we give highest precedence
    # to the last in the list)
    search_paths = [Path(p) for p in reversed(sys.path)]

    if Path(".") not in search_paths:
        search_paths.append(Path("."))

    for p in paths:
        path = Path(p).resolve(strict=True)
        search_paths.append(path)

    return search_paths


def compile_files(
    input_files: list[str],
    output_formats: OutputFormats,
    paths: list[str] = None,
    show_gas_estimates: bool = False,
    settings: Optional[Settings] = None,
    storage_layout_paths: list[str] = None,
    no_bytecode_metadata: bool = False,
) -> dict:
    search_paths = get_search_paths(paths)
    input_bundle = FilesystemInputBundle(search_paths)

    show_version = False
    if "combined_json" in output_formats:
        if len(output_formats) > 1:
            raise ValueError("If using combined_json it must be the only output format requested")
        output_formats = combined_json_outputs
        show_version = True

    translate_map = {
        "abi_python": "abi",
        "json": "abi",
        "ast": "ast_dict",
        "annotated_ast": "annotated_ast_dict",
        "ir_json": "ir_dict",
    }
    final_formats = [translate_map.get(i, i) for i in output_formats]

    if storage_layout_paths:
        if len(storage_layout_paths) != len(input_files):
            raise ValueError(
                "provided {len(storage_layout_paths)} storage "
                "layouts, but {len(input_files)} source files"
            )

    ret: dict[Any, Any] = {}
    if show_version:
        ret["version"] = vyper.__version__

    for file_name in input_files:
        file_path = Path(file_name)
        file = input_bundle.load_file(file_path)
        assert isinstance(file, FileInput)  # mypy hint

        storage_layout_override = None
        if storage_layout_paths:
            storage_file_path = storage_layout_paths.pop(0)
            with open(storage_file_path) as sfh:
                storage_layout_override = json.load(sfh)

        output = vyper.compile_from_file_input(
            file,
            input_bundle=input_bundle,
            output_formats=final_formats,
            exc_handler=exc_handler,
            settings=settings,
            storage_layout_override=storage_layout_override,
            show_gas_estimates=show_gas_estimates,
            no_bytecode_metadata=no_bytecode_metadata,
        )

        ret[file_path] = output

    return ret


if __name__ == "__main__":
    _parse_args(sys.argv[1:])
