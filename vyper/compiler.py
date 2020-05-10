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
    opcodes,
    optimizer,
)
from vyper.ast import (
    ast_to_dict,
    parse_natspec,
    parse_to_ast,
)
from vyper.opcodes import (
    DEFAULT_EVM_VERSION,
    evm_wrapper,
)
from vyper.parser import (
    parser,
)
from vyper.parser.global_context import (
    GlobalContext,
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


class CompilerData:

    def __init__(self, contract_name, source_code, interface_sources, source_id):
        self.contract_name = contract_name
        self.source_code = source_code
        self.interface_sources = interface_sources
        self.source_id = source_id

    @property
    def vyper_ast(self):
        if not hasattr(self, "_vyper_ast"):
            self._vyper_ast = generate_ast(
                self.source_code, self.interface_sources, self.source_id
            )
        return self._vyper_ast

    @property
    def global_ctx(self):
        if not hasattr(self, "_vyper_ast"):
            self._global_ctx = generate_global_context(
                self.source_code, self.interface_sources, self.source_id, self.vyper_ast
            )
        return self._global_ctx

    def _gen_lll(self):
        self._lll_nodes, self._lll_runtime = generate_lll_nodes(self.source_code, self.global_ctx)

    @property
    def lll_nodes(self):
        if not hasattr(self, "_lll_nodes"):
            self._gen_lll()
        return self._lll_nodes

    @property
    def lll_runtime(self):
        if not hasattr(self, "_lll_runtime"):
            self._gen_lll()
        return self._lll_runtime

    @property
    def assembly(self):
        if not hasattr(self, "_assembly"):
            self._assembly = generate_assembly(self.lll_nodes)
        return self._assembly

    @property
    def assembly_runtime(self):
        if not hasattr(self, "_assembly_runtime"):
            self._assembly_runtime = generate_assembly(self.lll_runtime)
        return self._assembly_runtime

    @property
    def bytecode(self):
        if not hasattr(self, "_bytecode"):
            self._bytecode = generate_bytecode(self.assembly)
        return self._bytecode

    @property
    def bytecode_runtime(self):
        if not hasattr(self, "_assembly_runtime"):
            self._bytecode_runtime = generate_bytecode(self.assembly_runtime)
        return self._bytecode_runtime


# pure compiler-pass functions

def generate_ast(source_code, interface_codes, source_id):
    return parse_to_ast(source_code, source_id)


def generate_global_context(source_code, interface_codes, source_id, vyper_ast):
    return GlobalContext.get_global_context(vyper_ast, interface_codes=interface_codes)


def generate_lll_nodes(source_code, global_ctx):
    lll_nodes, lll_runtime = parser.parse_tree_to_lll(source_code, global_ctx)
    lll_nodes = optimizer.optimize(lll_nodes)
    lll_runtime = optimizer.optimize(lll_runtime)
    return lll_nodes, lll_runtime


def generate_assembly(lll_nodes):
    assembly = compile_lll.compile_to_assembly(lll_nodes)
    if _find_nested_opcode(assembly, 'DEBUG'):
        warnings.warn(
            'This code contains DEBUG opcodes! The DEBUG opcode will only work in '
            'a supported EVM! It will FAIL on all other nodes!'
        )
    return assembly


def _find_nested_opcode(assembly, key):
    if key in assembly:
        return True
    else:
        sublists = [sub for sub in assembly if isinstance(sub, list)]
        return any(_find_nested_opcode(x, key) for x in sublists)


def generate_bytecode(assembly):
    return compile_lll.assembly_to_evm(assembly)[0]


# output generation functions

def build_ast_dict(compiler_data):
    ast_dict = {
        'contract_name': compiler_data.contract_name,
        'ast': ast_to_dict(compiler_data.vyper_ast)
    }
    return ast_dict


def build_devdoc(compiler_data):
    userdoc, devdoc = parse_natspec(compiler_data.vyper_ast, compiler_data.global_ctx)
    return devdoc


def build_userdoc(compiler_data):
    userdoc, devdoc = parse_natspec(compiler_data.vyper_ast, compiler_data.global_ctx)
    return userdoc


def build_external_interface_output(compiler_data):
    return extract_external_interface(compiler_data.global_ctx, compiler_data.contract_name)


def build_interface_output(compiler_data):
    return extract_interface_str(compiler_data.global_ctx)


def build_ir_output(compiler_data):
    return compiler_data.lll_nodes


def build_method_identifiers_output(compiler_data):
    return sig_utils.mk_method_identifiers(compiler_data.global_ctx)


def build_abi_output(compiler_data):
    abi = sig_utils.mk_full_signature(compiler_data.global_ctx)
    # Add gas estimates for each function to ABI
    gas_estimates = _build_gas_estimate(compiler_data.lll_nodes)
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


def _build_gas_estimate(lll_nodes):
    gas_estimates = {}

    # Extract the stuff inside the LLL bracket
    if lll_nodes.value == 'seq':
        if len(lll_nodes.args) > 0 and lll_nodes.args[-1].value == 'return':
            lll_nodes = lll_nodes.args[-1].args[1].args[0]

    assert lll_nodes.value == 'seq'
    for arg in lll_nodes.args:
        if arg.func_name is not None:
            gas_estimates[arg.func_name] = arg.total_gas

    return gas_estimates


def build_asm_output(compiler_data):
    return _build_asm(compiler_data.assembly)


def _build_asm(asm_list):
    output_string = ''
    skip_newlines = 0
    for node in asm_list:
        if isinstance(node, list):
            output_string += _build_asm(node)
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


def build_source_map_output(compiler_data):
    _, line_number_map = compile_lll.assembly_to_evm(compiler_data.assembly_runtime)
    # Sort line_number_map
    out = OrderedDict()
    for k in sorted(line_number_map.keys()):
        out[k] = line_number_map[k]

    out['pc_pos_map_compressed'] = _compress_source_map(
        compiler_data.source_code,
        out['pc_pos_map'],
        out['pc_jump_map'],
        compiler_data.source_id
    )
    out['pc_pos_map'] = dict((k, v) for k, v in out['pc_pos_map'].items() if v)
    return out


def _compress_source_map(code, pos_map, jump_map, source_id):
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


def build_bytecode_output(compiler_data):
    return f"0x{compiler_data.bytecode.hex()}"


def build_bytecode_runtime_output(compiler_data):
    return f"0x{compiler_data.bytecode_runtime.hex()}"


def build_opcodes_output(compiler_data):
    return _build_opcodes(compiler_data.bytecode)


def build_opcodes_runtime_output(compiler_data):
    return _build_opcodes(compiler_data.bytecode_runtime)


def _build_opcodes(bytecode):
    bytecode = bytecode.hex().upper()
    bytecode = deque(bytecode[i:i + 2] for i in range(0, len(bytecode), 2))
    opcode_map = dict((v[0], k) for k, v in opcodes.get_opcodes().items())
    opcode_str = ""

    while bytecode:
        op = int(bytecode.popleft(), 16)
        opcode_str += opcode_map[op] + " "
        if "PUSH" not in opcode_map[op]:
            continue
        push_len = int(opcode_map[op][4:])
        opcode_str += "0x" + "".join(bytecode.popleft() for i in range(push_len)) + " "

    return opcode_str[:-1]


OUTPUT_FORMATS = {
    # requires vyper_ast
    'ast_dict': build_ast_dict,
    # requires global_ctx
    'devdoc': build_devdoc,
    'userdoc': build_userdoc,
    # requires lll_node
    'external_interface': build_external_interface_output,
    'interface': build_interface_output,
    'ir': build_ir_output,
    'method_identifiers': build_method_identifiers_output,
    # requires assembly
    'abi': build_abi_output,
    'asm': build_asm_output,
    'source_map': build_source_map_output,
    # requires bytecode
    'bytecode': build_bytecode_output,
    'bytecode_runtime': build_bytecode_runtime_output,
    'opcodes': build_opcodes_output,
    'opcodes_runtime': build_opcodes_runtime_output,
}


@evm_wrapper
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
        # trailing newline fixes python parsing bug when source ends in a comment
        # https://bugs.python.org/issue35107
        source_code = f"{contract_sources[contract_name]}\n"
        interfaces: Any = interface_codes
        if (
            isinstance(interfaces, dict) and
            contract_name in interfaces and
            isinstance(interfaces[contract_name], dict)
        ):
            interfaces = interfaces[contract_name]

        compiler_data = CompilerData(contract_name, source_code, interfaces, source_id)
        for output_format in output_formats[contract_name]:
            if output_format not in OUTPUT_FORMATS:
                raise ValueError(f'Unsupported format type {repr(output_format)}')
            try:
                out.setdefault(contract_name, {})
                out[contract_name][output_format] = OUTPUT_FORMATS[output_format](compiler_data)
            except Exception as exc:
                if exc_handler is not None:
                    exc_handler(contract_name, exc)
                else:
                    raise exc

    return out


UNKNOWN_CONTRACT_NAME = '<unknown>'


def compile_code(code,
                 output_formats=None,
                 interface_codes=None,
                 evm_version=DEFAULT_EVM_VERSION):

    contract_sources = {UNKNOWN_CONTRACT_NAME: code}

    return compile_codes(
        contract_sources,
        output_formats,
        interface_codes=interface_codes,
        evm_version=evm_version
    )[UNKNOWN_CONTRACT_NAME]


# TODO can these live somewhere else?
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
