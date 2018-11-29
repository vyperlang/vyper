from vyper.parser import parser
from vyper import compile_lll
from vyper import optimizer
from collections import OrderedDict


def __compile(code, *args, **kwargs):
    lll = optimizer.optimize(parser.parse_tree_to_lll(parser.parse(code), code, runtime_only=kwargs.get('bytecode_runtime', False)))
    asm = compile_lll.compile_to_assembly(lll)

    def find_nested_opcode(asm_list, key):
        if key in asm_list:
            return True
        else:
            sublists = [sub for sub in asm_list if isinstance(sub, list)]
            return any([find_nested_opcode(x, key) for x in sublists])

    if find_nested_opcode(asm, 'DEBUG'):
        print('Please note this code contains DEBUG opcode.')
        print('This will only work in a support EVM. This FAIL on any other nodes.')

    c, line_number_map = compile_lll.assembly_to_evm(asm)
    return c


def gas_estimate(origcode, *args, **kwargs):
    o = {}
    code = optimizer.optimize(parser.parse_to_lll(origcode))

    # Extract the stuff inside the LLL bracket
    if code.value == 'seq':
        if len(code.args) > 0 and code.args[-1].value == 'return':
            code = code.args[-1].args[1].args[0]

    assert code.value == 'seq'
    for arg in code.args:
        if hasattr(arg, 'func_name'):
            o[arg.func_name] = arg.total_gas
    return o


def mk_full_signature(code, *args, **kwargs):
    abi = parser.mk_full_signature(parser.parse(code))
    # Add gas estimates for each function to ABI
    gas_estimates = gas_estimate(code)
    for idx, func in enumerate(abi):
        func_name = func['name'].split('(')[0]
        # Skip __init__, has no estimate
        if func_name in gas_estimates and func_name != '__init__':
            abi[idx]['gas'] = gas_estimates[func_name]
    return abi


def get_asm(asm_list):
    output_string = ''
    skip_newlines = 0
    for node in asm_list:
        if isinstance(node, list):
            output_string += get_asm(node)
            continue

        is_push = isinstance(node, str) and node.startswith('PUSH')

        output_string += str(node) + ' '
        if skip_newlines:
            skip_newlines -= 1
        elif is_push:
            skip_newlines = int(node[4:]) - 1
        else:
            output_string += '\n'
    return output_string


def get_source_map(code):
    asm_list = compile_lll.compile_to_assembly(optimizer.optimize(parser.parse_to_lll(code, runtime_only=True)))
    c, line_number_map = compile_lll.assembly_to_evm(asm_list)
    # Sort line_number_map
    out = OrderedDict()
    keylist = line_number_map.keys()
    for k in sorted(keylist):
        out[k] = line_number_map[k]
    return out


output_formats_map = {
    'abi': lambda code: mk_full_signature(code),
    'bytecode': lambda code: '0x' + __compile(code).hex(),
    'bytecode_runtime': lambda code: '0x' + __compile(code, bytecode_runtime=True).hex(),
    'ir': lambda code: optimizer.optimize(parser.parse_to_lll(code)),
    'asm': lambda code: get_asm(compile_lll.compile_to_assembly(optimizer.optimize(parser.parse_to_lll(code)))),
    'source_map': get_source_map,
    'method_identifiers': lambda code: parser.mk_method_identifiers(code)
}


def compile_codes(codes, output_formats=['bytecode'], output_type='list', exc_handler=None):

    out = OrderedDict()
    for contract_name, code in codes.items():
        for output_format in output_formats:
            if output_format not in output_formats_map:
                raise Exception('Unsupported format type %s.' % output_format)

            try:
                out.setdefault(contract_name, {})[output_format] = output_formats_map[output_format](code)
            except Exception as exc:
                if exc_handler:
                    exc_handler(contract_name, exc)
                else:
                    raise exc

    if output_type == 'list':
        return [v for v in out.values()]
    elif output_type == 'dict':
        return out
    else:
        raise Exception('Unknown output_type')


def compile_code(code, output_formats=['bytecode']):
    codes = {'': code}
    return compile_codes(codes, output_formats, 'list')[0]
