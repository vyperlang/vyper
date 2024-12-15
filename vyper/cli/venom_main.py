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
    parser.add_argument(
        "input_file",
        nargs="?",
        help="path to the Venom source file (required if --stdin is not used)",
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
    parser.add_argument(
        "--stdin", action="store_true", help="read the Venom source code from standard input"
    )

    args = parser.parse_args(argv)

    if args.evm_version is not None:
        set_global_settings(Settings(evm_version=args.evm_version))

    elif args.input_file:
        try:
            with open(args.input_file, "r") as f:
                venom_source = f.read()
        except FileNotFoundError:
            print(f"Error: File '{args.input_file}' not found.")
            sys.exit(1)
        except IOError as e:
            print(f"Error: Unable to read file '{args.input_file}': {e}")
            sys.exit(1)
    else:
        print("Error: No input file provided. Either use --stdin or provide a file path.")
        sys.exit(1)

    process_venom_source(venom_source)


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
    _parse_args(sys.argv[1:])
