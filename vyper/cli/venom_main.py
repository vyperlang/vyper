#!/usr/bin/env python3
import argparse
import sys

import vyper
import vyper.evm.opcodes as evm
from vyper.compiler.phases import generate_bytecode
from vyper.compiler.settings import OptimizationLevel, Settings, set_global_settings
from vyper.venom import generate_assembly_experimental, run_passes_on
from vyper.venom.parser import parse_venom

"""
Standalone entry point into venom compiler. Parses venom input and emits
bytecode.
"""


def _parse_cli_args():
    return _parse_args(sys.argv[1:])


def _parse_args(argv: list[str]):
    usage = (
        f"venom [-h] [--version] [--evm-version {{{','.join(evm.EVM_VERSIONS)}}}] "
        "[--stdin | input_file]"
    )
    parser = argparse.ArgumentParser(
        description="Venom EVM IR parser & compiler",
        usage=usage,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "input_file",
        nargs="?",
        help="path to the Venom source file (required if --stdin is not used)",
    )
    group.add_argument(
        "--stdin", action="store_true", help="read the Venom source code from standard input"
    )

    parser.add_argument(
        "--version",
        action="version",
        version=vyper.__long_version__,
        help="display the version of the Vyper compiler",
    )
    parser.add_argument(
        "--evm-version",
        help=f"select the desired EVM version (default {evm.DEFAULT_EVM_VERSION})",
        choices=list(evm.EVM_VERSIONS),
        dest="evm_version",
    )

    args = parser.parse_args(argv)

    if args.evm_version:
        set_global_settings(Settings(evm_version=args.evm_version))

    if args.stdin:
        venom_source = read_from_stdin()
    elif args.input_file:
        venom_source = read_from_file(args.input_file)

    process_venom_source(venom_source)


def read_from_stdin():
    if not sys.stdin.isatty():
        return sys.stdin.read()
    else:
        print("Error: --stdin flag used but no input provided.")
        sys.exit(1)


def read_from_file(input_file):
    try:
        with open(input_file, "r") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: File '{input_file}' not found.")
        sys.exit(1)
    except IOError as e:
        print(f"Error: Unable to read file '{input_file}': {e}")
        sys.exit(1)


def process_venom_source(source: str):
    try:
        ctx = parse_venom(source)
        run_passes_on(ctx, OptimizationLevel.default())
        asm = generate_assembly_experimental(ctx)
        bytecode = generate_bytecode(asm, compiler_metadata=None)
        print(f"0x{bytecode.hex()}")
    except Exception as e:
        print(f"Error: Compilation failed: {e}.")
        sys.exit(1)


if __name__ == "__main__":
    _parse_cli_args()
