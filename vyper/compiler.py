from vyper.parser import parser
from . import compile_lll
from . import optimizer


def compile(code, *args, **kwargs):
    lll = optimizer.optimize(parser.parse_tree_to_lll(parser.parse(code), code, runtime_only=kwargs.get('bytecode_runtime', False)))
    return compile_lll.assembly_to_evm(compile_lll.compile_to_assembly(lll))


def gas_estimate(origcode, *args, **kwargs):
    o = {}
    code = optimizer.optimize(parser.parse_to_lll(origcode))

    # Extract the stuff inside the LLL bracket
    if code.value == 'seq':
        if code.args[-1].value == 'return':
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
