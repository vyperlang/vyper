#!/usr/bin/env python3
import argparse
import functools
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import vyper
import vyper.codegen.ir_node as ir_node
import vyper.evm.opcodes as evm
from vyper.cli import vyper_json
from vyper.cli.compile_archive import NotZipInput, compile_from_zip
from vyper.compiler.input_bundle import FileInput, FilesystemInputBundle
from vyper.compiler.settings import VYPER_TRACEBACK_LIMIT, OptimizationLevel, Settings
from vyper.typing import ContractPath, OutputFormats
from vyper.utils import uniq
from vyper.warnings import warnings_filter

format_options_help = """Format to print, one or more of (comma-separated):
bytecode (default) - Deployable bytecode
bytecode_runtime   - Bytecode at runtime
blueprint_bytecode - Deployment bytecode for an ERC-5202 compatible blueprint
abi                - ABI in JSON format
abi_python         - ABI in python format
source_map         - Vyper source map of deployable bytecode
source_map_runtime - Vyper source map of runtime bytecode
method_identifiers - Dictionary of method signature to method identifier
userdoc            - Natspec user documentation
devdoc             - Natspec developer documentation
metadata           - Contract metadata (intended for use by tooling developers)
combined_json      - All of the above format options combined as single JSON output
layout             - Storage layout of a Vyper contract
ast                - AST (not yet annotated) in JSON format
annotated_ast      - Annotated AST in JSON format
cfg                - Control flow graph of deployable bytecode
cfg_runtime        - Control flow graph of runtime bytecode
interface          - Vyper interface of a contract
external_interface - External interface of a contract, used for outside contract calls
opcodes            - List of opcodes as a string
opcodes_runtime    - List of runtime opcodes as a string
ir                 - Intermediate representation in list format
ir_json            - Intermediate representation in JSON format
ir_runtime         - Intermediate representation of runtime bytecode in list format
bb                 - Basic blocks of Venom IR for deployable bytecode
bb_runtime         - Basic blocks of Venom IR for runtime bytecode
asm                - Output the EVM assembly of the deployable bytecode
integrity          - Output the integrity hash of the source code
archive            - Output the build as an archive file
solc_json          - Output the build in solc json format
settings           - Output the settings for a given build in json format
"""

combined_json_outputs = [
    "bytecode",
    "bytecode_runtime",
    "blueprint_bytecode",
    "abi",
    "layout",
    "source_map",
    "source_map_runtime",
    "method_identifiers",
    "userdoc",
    "devdoc",
    "settings_dict",
]


def _parse_cli_args():
    return _parse_args(sys.argv[1:])


def _cli_helper(f, output_formats, compiled):
    if output_formats == ("combined_json",):
        compiled = {str(path): v for (path, v) in compiled.items()}
        print(json.dumps(compiled), file=f)
        return

    if output_formats == ("archive",):
        for contract_data in compiled.values():
            assert list(contract_data.keys()) == ["archive"]
            out = contract_data["archive"]
            if f.isatty() and isinstance(out, bytes):
                raise RuntimeError(
                    "won't write raw bytes to a tty! (if you want to base64"
                    " encode the archive, you can try `-f archive` in"
                    " conjunction with `--base64`)"
                )
            else:
                f.write(out)
        return

    for contract_data in compiled.values():
        for data in contract_data.values():
            if isinstance(data, (list, dict)):
                print(json.dumps(data), file=f)
            else:
                print(data, file=f)


def _parse_args(argv):
    if "--standard-json" in argv:
        argv.remove("--standard-json")
        vyper_json._parse_args(argv)
        return

    parser = argparse.ArgumentParser(
        description="Pythonic Smart Contract Language for the EVM",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("input_files", help="Vyper sourcecode to compile", nargs="+")
    parser.add_argument("--version", action="version", version=vyper.__long_version__)
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
        help=f"Select desired EVM version (default {evm.DEFAULT_EVM_VERSION})",
        choices=list(evm.EVM_VERSIONS),
        dest="evm_version",
    )
    parser.add_argument("--no-optimize", help="Do not optimize", action="store_true")
    parser.add_argument(
        "--base64",
        help="Base64 encode the output (only valid in conjunction with `-f archive`",
        action="store_true",
    )
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
    parser.add_argument(
        "--hex-ir", help="Represent integers as hex values in the IR", action="store_true"
    )
    parser.add_argument(
        "--path",
        "-p",
        help="Add a path to the compiler's search path",
        action="append",
        dest="paths",
    )
    parser.add_argument(
        "--disable-sys-path", help="Disable the use of sys.path", action="store_true"
    )

    parser.add_argument("-o", help="Set the output path", dest="output_path")
    parser.add_argument(
        "--experimental-codegen",
        "--venom-experimental",
        help="The compiler uses the new IR codegen. This is an experimental feature.",
        action="store_true",
        dest="experimental_codegen",
    )
    parser.add_argument("--enable-decimals", help="Enable decimals", action="store_true")

    parser.add_argument(
        "-W", help="Control warnings", dest="warnings_control", choices=["error", "none"]
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

    if args.base64 and output_formats != ("archive",):
        raise ValueError("Cannot use `--base64` except with `-f archive`")

    if args.base64:
        output_formats = ("archive_b64",)

    if args.no_optimize and args.optimize:
        raise ValueError("Cannot use `--no-optimize` and `--optimize` at the same time!")

    settings = Settings()

    # TODO: refactor to something like Settings.from_args()
    if args.no_optimize:
        settings.optimize = OptimizationLevel.NONE
    elif args.optimize is not None:
        settings.optimize = OptimizationLevel.from_string(args.optimize)

    if args.evm_version:
        settings.evm_version = args.evm_version

    if args.experimental_codegen:
        settings.experimental_codegen = args.experimental_codegen

    if args.debug:
        settings.debug = args.debug

    if args.enable_decimals:
        settings.enable_decimals = args.enable_decimals

    if args.verbose:
        print(f"cli specified: `{settings}`", file=sys.stderr)

    include_sys_path = not args.disable_sys_path

    compiled = compile_files(
        args.input_files,
        output_formats,
        args.paths,
        include_sys_path,
        args.show_gas_estimates,
        settings,
        args.storage_layout,
        args.no_bytecode_metadata,
        args.warnings_control,
    )

    mode = "w"
    if output_formats == ("archive",):
        mode = "wb"

    if args.output_path:
        with open(args.output_path, mode) as f:
            _cli_helper(f, output_formats, compiled)
    else:
        # https://stackoverflow.com/a/54073813
        with os.fdopen(sys.stdout.fileno(), mode, closefd=False) as f:
            _cli_helper(f, output_formats, compiled)


def exc_handler(contract_path: ContractPath, exception: Exception) -> None:
    print(f"Error compiling: {contract_path}")
    raise exception


def get_search_paths(paths: list[str] = None, include_sys_path=True) -> list[Path]:
    # given `paths` input, get the full search path, including
    # the system search path.
    paths = paths or []

    # lowest precedence search path is always sys path
    # note python sys path uses opposite resolution order from us
    # (first in list is highest precedence; we give highest precedence
    # to the last in the list)
    search_paths = []
    if include_sys_path:
        search_paths = [Path(p) for p in reversed(sys.path)]

    if Path(".") not in search_paths:
        search_paths.append(Path("."))

    for p in paths:
        path = Path(p).resolve(strict=True)
        search_paths.append(path)

    return search_paths


def _apply_warnings_filter(func):
    @functools.wraps(func)
    def inner(*args, **kwargs):
        # find "warnings_control" argument
        ba = inspect.signature(func).bind(*args, **kwargs)
        ba.apply_defaults()

        warnings_control = ba.arguments["warnings_control"]
        with warnings_filter(warnings_control):
            return func(*args, **kwargs)

    return inner


@_apply_warnings_filter
def compile_files(
    input_files: list[str],
    output_formats: OutputFormats,
    paths: list[str] = None,
    include_sys_path: bool = True,
    show_gas_estimates: bool = False,
    settings: Optional[Settings] = None,
    storage_layout_paths: list[str] = None,
    no_bytecode_metadata: bool = False,
    warnings_control: Optional[str] = None,
) -> dict:
    search_paths = get_search_paths(paths, include_sys_path)
    input_bundle = FilesystemInputBundle(search_paths)

    show_version = False
    if "combined_json" in output_formats:
        if len(output_formats) > 1:
            raise ValueError("If using combined_json it must be the only output format requested")
        output_formats = combined_json_outputs
        show_version = True

    # formats which can only be requested as a single output format
    for c in ("solc_json", "archive"):
        if c in output_formats and len(output_formats) > 1:
            raise ValueError(f"If using {c} it must be the only output format requested")

    translate_map = {
        "abi_python": "abi",
        "json": "abi",
        "ast": "ast_dict",
        "annotated_ast": "annotated_ast_dict",
        "ir_json": "ir_dict",
        "settings": "settings_dict",
    }
    final_formats = [translate_map.get(i, i) for i in output_formats]

    if storage_layout_paths:
        if len(storage_layout_paths) != len(input_files):
            raise ValueError(
                f"provided {len(storage_layout_paths)} storage "
                f"layouts, but {len(input_files)} source files"
            )

    ret: dict[Any, Any] = {}
    if show_version:
        ret["version"] = vyper.__version__

    for file_name in input_files:
        file_path = Path(file_name)

        try:
            # try to compile in zipfile mode if it's a zip file, falling back
            # to regular mode if it's not.
            # we allow this instead of requiring a different mode (like
            # `--zip`) so that verifier pipelines do not need a different
            # workflow for archive files and single-file contracts.
            output = compile_from_zip(file_name, final_formats, settings, no_bytecode_metadata)
            ret[file_path] = output
            continue
        except NotZipInput:
            pass

        # note compile_from_zip also reads the file contents, so this
        # is slightly inefficient (and also maybe allows for some very
        # rare, strange race conditions if the file changes in between
        # the two reads).
        file = input_bundle.load_file(file_path)
        assert isinstance(file, FileInput)  # mypy hint

        storage_layout_override = None
        if storage_layout_paths:
            storage_file_path = storage_layout_paths.pop(0)
            storage_layout_override = input_bundle.load_json_file(storage_file_path)

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
