from collections import (
    OrderedDict,
    deque,
)

from vyper import (
    compile_lll,
    optimizer,
)
from vyper.ast_utils import (
    ast_to_dict,
)
from vyper.opcodes import (
    opcodes,
)
from vyper.parser import (
    parser,
)
from vyper.signatures import (
    sig_utils,
)
from vyper.signatures.interface import (
    extract_external_interface,
    extract_interface_str,
)


def __compile(code, interface_codes=None, *args, **kwargs):
    lll = optimizer.optimize(
        parser.parse_tree_to_lll(
            parser.parse_to_ast(code),
            code,
            interface_codes=interface_codes,
            runtime_only=kwargs.get('bytecode_runtime', False)
        )
    )
    asm = compile_lll.compile_to_assembly(lll)

    def find_nested_opcode(asm_list, key):
        if key in asm_list:
            return True
        else:
            sublists = [sub for sub in asm_list if isinstance(sub, list)]
            return any(find_nested_opcode(x, key) for x in sublists)

    if find_nested_opcode(asm, 'DEBUG'):
        print('Please note this code contains DEBUG opcode.')
        print('This will only work in a support EVM. This FAIL on any other nodes.')

    c, line_number_map = compile_lll.assembly_to_evm(asm)
    return c


def gas_estimate(origcode, *args, **kwargs):
    o = {}
    code = optimizer.optimize(parser.parse_to_lll(origcode, *args, **kwargs))

    # Extract the stuff inside the LLL bracket
    if code.value == 'seq':
        if len(code.args) > 0 and code.args[-1].value == 'return':
            code = code.args[-1].args[1].args[0]

    assert code.value == 'seq'
    for arg in code.args:
        if arg.func_name is not None:
            o[arg.func_name] = arg.total_gas
    return o


def mk_full_signature(code, *args, **kwargs):
    abi = sig_utils.mk_full_signature(parser.parse_to_ast(code), *args, **kwargs)
    # Add gas estimates for each function to ABI
    gas_estimates = gas_estimate(code, *args, **kwargs)
    for func in abi:
        try:
            func_signature = func['name']
        except KeyError:
            # constructor and fallback functions don't have a name
            continue

        func_name, _, _ = func_signature.partition('(')
        # This check ensures we skip __init__ since it has no estimate
        if func_name in gas_estimates:
            # TODO: mutation
            func['gas'] = gas_estimates[func_name]
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


def get_source_map(code, contract_name, interface_codes=None):
    asm_list = compile_lll.compile_to_assembly(
        optimizer.optimize(
            parser.parse_to_lll(
                code,
                runtime_only=True,
                interface_codes=interface_codes)))
    c, line_number_map = compile_lll.assembly_to_evm(asm_list)
    # Sort line_number_map
    out = OrderedDict()
    keylist = line_number_map.keys()
    for k in sorted(keylist):
        out[k] = line_number_map[k]
    return out


def get_opcodes(code, contract_name, bytecodes_runtime=False, interface_codes=None):
    bytecode = __compile(
        code,
        bytecode_runtime=bytecodes_runtime,
        interface_codes=interface_codes
    ).hex().upper()
    bytecode = deque(bytecode[i:i + 2] for i in range(0, len(bytecode), 2))
    opcode_map = dict((v[0], k) for k, v in opcodes.items())
    opcode_str = ""

    while bytecode:
        op = int(bytecode.popleft(), 16)
        opcode_str += opcode_map[op] + " "
        if "PUSH" not in opcode_map[op]:
            continue
        push_len = int(opcode_map[op][4:])
        opcode_str += "0x" + "".join(bytecode.popleft() for i in range(push_len)) + " "

    return opcode_str[:-1]


def _mk_abi_output(code, contract_name, interface_codes):
    return mk_full_signature(code, interface_codes=interface_codes)


def _mk_bytecode_output(code, contract_name, interface_codes):
    return '0x' + __compile(code, interface_codes=interface_codes).hex()


def _mk_bytecode_runtime_output(code, contract_name, interface_codes):
    return '0x' + __compile(code, bytecode_runtime=True, interface_codes=interface_codes).hex()


def _mk_ir_output(code, contract_name, interface_codes):
    return optimizer.optimize(parser.parse_to_lll(code, interface_codes=interface_codes))


def _mk_asm_output(code, contract_name, interface_codes):
    return get_asm(compile_lll.compile_to_assembly(
        optimizer.optimize(parser.parse_to_lll(code, interface_codes=interface_codes))
    ))


def _mk_source_map_output(code, contract_name, interface_codes):
    return get_source_map(code, contract_name, interface_codes=interface_codes)


def _mk_method_identifiers_output(code, contract_name, interface_codes):
    return sig_utils.mk_method_identifiers(code, interface_codes=interface_codes)


def _mk_interface_output(code, contract_name, interface_codes):
    return extract_interface_str(code, contract_name, interface_codes=interface_codes)


def _mk_external_interface_output(code, contract_name, interface_codes):
    return extract_external_interface(code, contract_name, interface_codes=interface_codes)


def _mk_opcodes(code, contract_name, interface_codes):
    return get_opcodes(code, contract_name, interface_codes=interface_codes)


def _mk_opcodes_runtime(code, contract_name, interface_codes):
    return get_opcodes(code, contract_name, bytecodes_runtime=True, interface_codes=interface_codes)


def _mk_ast_dict(code, contract_name, interface_codes):
    o = {
        'contract_name': contract_name,
        'ast': ast_to_dict(parser.parse_to_ast(code))
    }
    return o


output_formats_map = {
    'abi': _mk_abi_output,
    'ast_dict': _mk_ast_dict,
    'bytecode': _mk_bytecode_output,
    'bytecode_runtime': _mk_bytecode_runtime_output,
    'ir': _mk_ir_output,
    'asm': _mk_asm_output,
    'source_map': _mk_source_map_output,
    'method_identifiers': _mk_method_identifiers_output,
    'interface': _mk_interface_output,
    'external_interface': _mk_external_interface_output,
    'opcodes': _mk_opcodes,
    'opcodes_runtime': _mk_opcodes_runtime,
}


def compile_codes(codes,
                  output_formats=None,
                  output_type='list',
                  exc_handler=None,
                  interface_codes=None):
    if output_formats is None:
        output_formats = ('bytecode',)

    out = OrderedDict()
    for contract_name, code in codes.items():
        for output_format in output_formats:
            if output_format not in output_formats_map:
                raise Exception('Unsupported format type %s.' % output_format)

            try:
                out.setdefault(contract_name, {})
                out[contract_name][output_format] = output_formats_map[output_format](
                    code=code,
                    contract_name=contract_name,
                    interface_codes=interface_codes,
                )
            except Exception as exc:
                if exc_handler is not None:
                    exc_handler(contract_name, exc)
                else:
                    raise exc

    if output_type == 'list':
        return [v for v in out.values()]
    elif output_type == 'dict':
        return out
    else:
        raise Exception('Unknown output_type')


def compile_code(code, output_formats=None, interface_codes=None):
    codes = {'': code}
    return compile_codes(codes, output_formats, 'list', interface_codes=interface_codes)[0]
