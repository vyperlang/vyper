#!/usr/bin/env python3
import argparse
import sys

import vyper
from vyper.codegen.ir_node import IRnode
from vyper.ir import compile_ir, optimizer
from vyper.ir.s_expressions import parse_s_exp


def _parse_cli_args():
    return _parse_args(sys.argv[1:])


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="Vyper IR IR compiler")
    parser.add_argument("input_file", help="Vyper sourcecode to compile")
    parser.add_argument(
        "--version", action="version", version=f"{vyper.__version__}+commit{vyper.__commit__}"
    )
    parser.add_argument(
        "-f",
        help="Format to print csv list of ir,opt_ir,asm,bytecode",
        default="bytecode",
        dest="format",
    )
    parser.add_argument(
        "--show-gas-estimates", help="Show gas estimates in ir output mode.", action="store_true"
    )

    args = parser.parse_args(argv)
    output_formats = set(dict.fromkeys(args.format.split(",")))
    compiler_data = compile_to_ir(args.input_file, output_formats, args.show_gas_estimates)

    for key in ("ir", "opt_ir", "asm", "bytecode"):
        if key in compiler_data:
            print(compiler_data[key])


def compile_to_ir(input_file, output_formats, show_gas_estimates=False):
    with open(input_file) as fh:
        s_expressions = parse_s_exp(fh.read())

    if show_gas_estimates:
        IRnode.repr_show_gas = True

    compiler_data = {}
    ir = IRnode.from_list(s_expressions[0])
    ir = optimizer.optimize(ir)
    if "ir" in output_formats:
        compiler_data["ir"] = ir

    asm = compile_ir.compile_to_assembly(ir)
    if "asm" in output_formats:
        compiler_data["asm"] = asm

    if "bytecode" in output_formats:
        (bytecode, _srcmap) = compile_ir.assembly_to_evm(asm)
        compiler_data["bytecode"] = "0x" + bytecode.hex()

    return compiler_data


if __name__ == "__main__":
    _parse_cli_args()
