#!/usr/bin/env python3
import argparse

import vyper
from vyper import (
    compile_lll,
    optimizer,
)
from vyper.parser.parser_utils import (
    LLLnode,
)
from vyper.parser.s_expressions import (
    parse_s_exp,
)


def _parse_cli_args():
    parser = argparse.ArgumentParser(description='Vyper LLL for Ethereum')
    parser.add_argument(
        'input_file',
        help='Vyper sourcecode to compile',
    )
    parser.add_argument(
        '--version',
        action='version',
        version='{0}'.format(vyper.__version__),
    )
    parser.add_argument(
        '-f',
        help='Format to print csv list of ir,opt_ir,asm,bytecode',
        default='bytecode',
        dest='format',
    )
    parser.add_argument(
        '--show-gas-estimates',
        help='Show gas estimates in ir output mode.',
        action='store_true',
    )

    args = parser.parse_args()
    output_formats = set(dict.fromkeys(args.format.split(',')))
    compiler_data = compile_to_lll(args.input_file, output_formats, args.show_gas_estimates)

    for key in ('ir', 'opt_ir', 'asm', 'bytecode'):
        if key in compiler_data:
            print(compiler_data[key])


def compile_to_lll(input_file, output_formats, show_gas_estimates=False):
    with open(input_file) as fh:
        s_expressions = parse_s_exp(fh.read())

    if show_gas_estimates:
        LLLnode.repr_show_gas = True

    compiler_data = {}
    lll = LLLnode.from_list(s_expressions[0])
    if 'ir' in output_formats:
        compiler_data['ir'] = lll

    if 'opt_ir' in output_formats:
        compiler_data['opt_ir'] = optimizer.optimize(lll)

    asm = compile_lll.compile_to_assembly(lll)
    if 'asm' in output_formats:
        compiler_data['asm'] = asm

    if 'bytecode' in output_formats:
        (bytecode, _srcmap) = compile_lll.assembly_to_evm(asm)
        compiler_data['bytecode'] = '0x' + bytecode.hex()

    return compiler_data
