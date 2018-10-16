from vyper.parser import parser
from vyper import compile_lll
from vyper import optimizer


def compile(code, *args, **kwargs):
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
