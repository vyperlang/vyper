from collections import (
    OrderedDict,
    deque,
)
from typing import (
    Any,
    Callable,
    Sequence,
    Union,
)
import warnings

import asttokens

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
from vyper.typing import (
    ContractCodes,
    InterfaceDict,
    InterfaceImports,
    OutputDict,
    OutputFormats,
)


def __compile(code, interface_codes=None, *args, **kwargs):
    ast = parser.parse_to_ast(code)
    lll = parser.parse_tree_to_lll(
        ast,
        code,
        interface_codes=interface_codes,
        runtime_only=kwargs.get('bytecode_runtime', False)
    )
    opt_lll = optimizer.optimize(lll)
    asm = compile_lll.compile_to_assembly(opt_lll)

    def find_nested_opcode(asm_list, key):
        if key in asm_list:
            return True
        else:
            sublists = [sub for sub in asm_list if isinstance(sub, list)]
            return any(find_nested_opcode(x, key) for x in sublists)

    if find_nested_opcode(asm, 'DEBUG'):
        warnings.warn(
            'This code contains DEBUG opcodes! The DEBUG opcode will only work in '
            'a supported EVM! It will FAIL on all other nodes!'
        )

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


def get_source_map(code, contract_name, interface_codes=None, runtime_only=True, source_id=0):
    asm_list = compile_lll.compile_to_assembly(
        optimizer.optimize(
            parser.parse_to_lll(
                code,
                runtime_only=runtime_only,
                interface_codes=interface_codes)))
    c, line_number_map = compile_lll.assembly_to_evm(asm_list)
    # Sort line_number_map
    out = OrderedDict()
    for k in sorted(line_number_map.keys()):
        out[k] = line_number_map[k]

    out['pc_pos_map_compressed'] = compress_source_map(
        code,
        out['pc_pos_map'],
        out['pc_jump_map'],
        source_id
    )
    out['pc_pos_map'] = dict((k, v) for k, v in out['pc_pos_map'].items() if v)
    return out


def compress_source_map(code, pos_map, jump_map, source_id):
    linenos = asttokens.LineNumbers(code)
    compressed_map = f"-1:-1:{source_id}:-;"
    last_pos = [-1, -1, source_id]

    for pc in sorted(pos_map)[1:]:
        current_pos = [-1, -1, source_id]
        if pos_map[pc]:
            current_pos[0] = linenos.line_to_offset(*pos_map[pc][:2])
            current_pos[1] = linenos.line_to_offset(*pos_map[pc][2:])-current_pos[0]

        if pc in jump_map:
            current_pos.append(jump_map[pc])

        for i in range(2, -1, -1):
            if current_pos[i] != last_pos[i]:
                last_pos[i] = current_pos[i]
            elif len(current_pos) == i+1:
                current_pos.pop()
            else:
                current_pos[i] = ""

        compressed_map += ":".join(str(i) for i in current_pos) + ";"

    return compressed_map


def expand_source_map(compressed_map):
    source_map = [_expand_row(i) if i else None for i in compressed_map.split(';')[:-1]]

    for i, value in enumerate(source_map[1:], 1):
        if value is None:
            source_map[i] = source_map[i - 1][:3] + [None]
            continue
        for x in range(3):
            if source_map[i][x] is None:
                source_map[i][x] = source_map[i - 1][x]

    return source_map


def _expand_row(row):
    result = [None] * 4
    for i, value in enumerate(row.split(':')):
        if value:
            result[i] = value if i == 3 else int(value)
    return result


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


def _mk_abi_output(code, contract_name, interface_codes, source_id):
    return mk_full_signature(code, interface_codes=interface_codes)


def _mk_bytecode_output(code, contract_name, interface_codes, source_id):
    return '0x' + __compile(code, interface_codes=interface_codes).hex()


def _mk_bytecode_runtime_output(code, contract_name, interface_codes, source_id):
    return '0x' + __compile(code, bytecode_runtime=True, interface_codes=interface_codes).hex()


def _mk_ir_output(code, contract_name, interface_codes, source_id):
    return optimizer.optimize(parser.parse_to_lll(code, interface_codes=interface_codes))


def _mk_asm_output(code, contract_name, interface_codes, source_id):
    return get_asm(compile_lll.compile_to_assembly(
        optimizer.optimize(parser.parse_to_lll(code, interface_codes=interface_codes))
    ))


def _mk_source_map_output(code, contract_name, interface_codes, source_id):
    return get_source_map(
        code,
        contract_name,
        interface_codes=interface_codes,
        runtime_only=True,
        source_id=source_id
    )


def _mk_method_identifiers_output(code, contract_name, interface_codes, source_id):
    return sig_utils.mk_method_identifiers(code, interface_codes=interface_codes)


def _mk_interface_output(code, contract_name, interface_codes, source_id):
    return extract_interface_str(code, contract_name, interface_codes=interface_codes)


def _mk_external_interface_output(code, contract_name, interface_codes, source_id):
    return extract_external_interface(code, contract_name, interface_codes=interface_codes)


def _mk_opcodes(code, contract_name, interface_codes, source_id):
    return get_opcodes(code, contract_name, interface_codes=interface_codes)


def _mk_opcodes_runtime(code, contract_name, interface_codes, source_id):
    return get_opcodes(code, contract_name, bytecodes_runtime=True, interface_codes=interface_codes)


def _mk_ast_dict(code, contract_name, interface_codes, source_id):
    o = {
        'contract_name': contract_name,
        'ast': ast_to_dict(parser.parse_to_ast(code, source_id))
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


def compile_codes(contract_sources: ContractCodes,
                  output_formats: Union[OutputDict, OutputFormats, None] = None,
                  exc_handler: Union[Callable, None] = None,
                  interface_codes: Union[InterfaceDict, InterfaceImports, None] = None,
                  initial_id: int = 0) -> OrderedDict:

    if output_formats is None:
        output_formats = ('bytecode',)
    if isinstance(output_formats, Sequence):
        output_formats = dict((k, output_formats) for k in contract_sources.keys())

    out: OrderedDict = OrderedDict()
    for source_id, contract_name in enumerate(sorted(contract_sources), start=initial_id):
        code = contract_sources[contract_name]
        for output_format in output_formats[contract_name]:
            if output_format not in output_formats_map:
                raise ValueError(f'Unsupported format type {repr(output_format)}')

            try:
                interfaces: Any = interface_codes
                if (
                    isinstance(interfaces, dict) and
                    contract_name in interfaces and
                    isinstance(interfaces[contract_name], dict)
                ):
                    interfaces = interfaces[contract_name]
                out.setdefault(contract_name, {})
                out[contract_name][output_format] = output_formats_map[output_format](
                    # trailing newline fixes python parsing bug when source ends in a comment
                    # https://bugs.python.org/issue35107
                    code=f"{code}\n",
                    contract_name=contract_name,
                    interface_codes=interfaces,
                    source_id=source_id
                )
            except Exception as exc:
                if exc_handler is not None:
                    exc_handler(contract_name, exc)
                else:
                    raise exc

    return out


UNKNOWN_CONTRACT_NAME = '<unknown>'


def compile_code(code, output_formats=None, interface_codes=None):
    contract_sources = {UNKNOWN_CONTRACT_NAME: code}

    return compile_codes(
        contract_sources,
        output_formats,
        interface_codes=interface_codes,
    )[UNKNOWN_CONTRACT_NAME]
