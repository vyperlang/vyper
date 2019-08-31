#!/usr/bin/env python3

from vyper.cli.vyper_json import (
    format_to_output_dict,
)
from vyper.compiler import (
    compile_codes,
    output_formats_map,
)

FOO_CODE = """
@public
def foo() -> bool:
    return True
"""


def test_keys():
    compiler_data = compile_codes(
        {'foo.vy': FOO_CODE},
        output_formats=list(output_formats_map.keys())
    )
    output_json = format_to_output_dict(compiler_data)
    data = compiler_data['foo.vy']
    assert output_json['sources']['foo.vy'] == {'id': 0, 'ast': data['ast_dict']['ast']}
    assert output_json['contracts']['foo.vy']['foo'] == {
        'abi': data['abi'],
        'interface': data['interface'],
        'ir': data['ir'],
        'evm': {
            'bytecode': {
                'object': data['bytecode'],
                'opcodes': data['opcodes']
            },
            'deployedBytecode': {
                'object': data['bytecode_runtime'],
                'opcodes': data['opcodes_runtime'],
                'sourceMap': data['source_map']['pc_pos_map_compressed']
            },
            'methodIdentifiers': data['method_identifiers'],
        }
    }
