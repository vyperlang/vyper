#!/usr/bin/env python3
import argparse
import sys

import vyper
import vyper.evm.opcodes as evm
from vyper.compiler.phases import generate_bytecode
from vyper.compiler.settings import OptimizationLevel, Settings, set_global_settings
from vyper.venom import generate_assembly_experimental, run_passes_on
from vyper.venom.check_venom import check_venom_ctx
from vyper.venom.parser import parse_venom

"""
Standalone entry point into venom compiler. Parses venom input and emits
bytecode.
"""


def _parse_cli_args():
    return _parse_args(sys.argv[1:])


def _parse_args(argv: list[str]):
    parser = argparse.ArgumentParser(
        description="Venom EVM IR parser & compiler", formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("input_file", help="Venom sourcefile", nargs="?")
    parser.add_argument("--version", action="version", version=vyper.__long_version__)
    parser.add_argument(
        "--evm-version",
        help=f"Select desired EVM version (default {evm.DEFAULT_EVM_VERSION})",
        choices=list(evm.EVM_VERSIONS),
        dest="evm_version",
    )
    parser.add_argument(
        "--stdin", action="store_true", help="whether to pull venom input from stdin"
    )

    args = parser.parse_args(argv)

    if args.evm_version is not None:
        set_global_settings(Settings(evm_version=args.evm_version))

    if args.stdin:
        if not sys.stdin.isatty():
            venom_source = sys.stdin.read()
        else:
            # No input provided
            print("Error: --stdin flag used but no input provided")
            sys.exit(1)
    else:
        if args.input_file is None:
            print("Error: No input file provided, either use --stdin or provide a path")
            sys.exit(1)
        with open(args.input_file, "r") as f:
            venom_source = f.read()

    ctx = parse_venom(venom_source)

    check_venom_ctx(ctx)

    run_passes_on(ctx, OptimizationLevel.default())
    asm = generate_assembly_experimental(ctx)
    bytecode, _ = generate_bytecode(asm)
    print(f"0x{bytecode.hex()}")


if __name__ == "__main__":
    _parse_args(sys.argv[1:])
