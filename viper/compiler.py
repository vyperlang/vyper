from . import parser
from . import compile_lll
from . import optimizer


def memsize_to_gas(memsize):
    return (memsize // 32) * 3 + (memsize // 32) ** 2 // 512


def compile(code, *args, **kwargs):
    lll = optimizer.optimize(parser.parse_tree_to_lll(parser.parse(code), code))
    return compile_lll.assembly_to_evm(compile_lll.compile_to_assembly(lll))


def mk_full_signature(code, *args, **kwargs):
    o = parser.mk_full_signature(parser.parse(code))
    return o


def gas_estimate(origcode, *args, **kwargs):
    o = {}
    code = optimizer.optimize(parser.parse_to_lll(origcode))
    # Extract the stuff inside the LLL bracket
    if code.value == 'seq':
        code = code.args[-1].args[1].args[0]
    else:
        code = code.args[1].args[0]
    assert code.value == 'seq'
    for arg in code.args:
        if hasattr(arg, 'func_name'):
            o[arg.func_name] = arg.total_gas
    return o


# Dummy object, as some tools expect this interface
class Compiler(object):

    def compile(self, code, *args, **kwargs):
        return compile(code, *args, **kwargs)

    def mk_full_signature(self, code, *args, **kwargs):
        return mk_full_signature(code, *args, **kwargs)

    def gas_estimate(self, code, *args, **kwargs):
        return gas_estimate(code, *args, **kwargs)
