#!/usr/bin/env python3
import argparse
import sys
import vyper
from vyper.venom.parser import parse_venom
from vyper.venom import generate_assembly_experimental, run_passes_on
from vyper.compiler.settings import OptimizationLevel
from vyper.compiler.phases import generate_bytecode


def _parse_cli_args():
    return _parse_args(sys.argv[1:])


def _parse_args(argv: list[str]):
    parser = argparse.ArgumentParser(
        description="Venom EVM IR parser & compiler",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("input_file", help="Venom sourcefile", nargs='?')
    parser.add_argument("--version", action="version", version=vyper.__long_version__)

    args = parser.parse_args(argv)

    if args.input_file is None:
        if not sys.stdin.isatty():
            venom_source = sys.stdin.read()
        else:
            # No input provided
            print("Error: No input provided")
            sys.exit(1)
    else:
        with open(args.input_file, 'r') as f:
            venom_source = f.read()

    ctx = parse_venom(venom_source)
    print(ctx)
    run_passes_on(ctx, OptimizationLevel.default())
    asm = generate_assembly_experimental(ctx)
    print(asm)
    bytecode = generate_bytecode(asm, compiler_metadata=None)
    print(bytecode.hex())


if __name__ == "__main__":
    _parse_args(sys.argv[1:])
