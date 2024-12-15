#!/usr/bin/env python3
import argparse
import sys
import os

import vyper
from vyper.codegen.ir_node import IRnode
from vyper.ir import compile_ir, optimizer
from vyper.ir.s_expressions import parse_s_exp


def _parse_cli_args():
    args = _parse_args(sys.argv[1:])
    output_formats = validate_output_formats(args.format)
    compiler_data = compile_to_ir(args.input_file, output_formats, args.show_gas_estimates)

    for key in ("ir", "opt_ir", "asm", "bytecode"):
        if key in compiler_data:
            print(compiler_data[key])


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="Legacy Vyper IR compiler")
    parser.add_argument("input_file", help="path to the Vyper IR source file (e.g., foo.lll)")
    parser.add_argument(
        "--version",
        action="version",
        version=vyper.__long_version__,
        help="display the version of the Vyper compiler",
    )
    parser.add_argument(
        "-f",
        help=(
            "comma-separated list of output formats to generate; "
            "valid options: ir, opt_ir, asm, bytecode (default: bytecode)"
        ),
        default="bytecode",
        dest="format",
    )
    parser.add_argument(
        "--show-gas-estimates",
        help="include gas estimates in IR output (only applicable to 'ir' format)",
        action="store_true",
    )
    return parser.parse_args(argv)


def validate_output_formats(format_str):
    valid_formats = {"ir", "opt_ir", "asm", "bytecode"}
    formats = set(format_str.split(","))
    invalid_formats = formats - valid_formats
    if invalid_formats:
        print(f"Error: Invalid output formats: {', '.join(invalid_formats)}")
        print(f"Valid options are: {', '.join(valid_formats)}")
        sys.exit(1)
    return formats


def compile_to_ir(input_file, output_formats, show_gas_estimates=False):
    if not os.path.exists(input_file):
        print(f"Error: File '{input_file}' does not exist.")
        sys.exit(1)

    try:
        with open(input_file, "r") as fh:
            s_expressions = parse_s_exp(fh.read())
    except Exception as e:
        print(f"Error: Unable to read or parse file '{input_file}': {e}")
        sys.exit(1)

    if show_gas_estimates and "ir" not in output_formats:
        print("Warning: --show-gas-estimates has no effect without 'ir' format.")
        show_gas_estimates = False

    if show_gas_estimates:
        IRnode.repr_show_gas = True

    compiler_data = {}
    ir = IRnode.from_list(s_expressions[0])
    ir = optimizer.optimize(ir)
    if "ir" in output_formats:
        compiler_data["ir"] = ir

    if "opt_ir" in output_formats:
        compiler_data["opt_ir"] = ir

    asm = compile_ir.compile_to_assembly(ir)
    if "asm" in output_formats:
        compiler_data["asm"] = asm

    if "bytecode" in output_formats:
        bytecode, _ = compile_ir.assembly_to_evm(asm)
        compiler_data["bytecode"] = "0x" + bytecode.hex()

    return compiler_data


if __name__ == "__main__":
    _parse_cli_args()
