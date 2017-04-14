from . import parser
from . import compile_lll
from . import optimizer

def memsize_to_gas(memsize):
    return (memsize // 32) * 3 + (memsize // 32) ** 2 // 512

initial_gas = compile_lll.gas_estimate(parser.mk_initial())
function_gas = compile_lll.gas_estimate(parser.parse_func(parser.parse('def foo(): pass')[0], {}, {}, 'def foo(): pass'))

def compile(code, *args, **kwargs):
    lll = optimizer.optimize(parser.parse_tree_to_lll(parser.parse(code), code))
    return compile_lll.assembly_to_evm(compile_lll.compile_to_assembly(lll))

def mk_full_signature(code, *args, **kwargs):
    o = parser.mk_full_signature(parser.parse(code))
    return o

def gas_estimate(origcode, *args, **kwargs):
    code = parser.parse(origcode)
    _defs, _globals = parser.get_defs_and_globals(code)
    o = {}
    sigs = {name: (ins, out, sig) for name, ins, out, sig in [parser.get_function_signature(_def) for _def in _defs]}
    for i, _def in enumerate(_defs):
        name, args, output_type, const, sig, method_id = parser.get_func_details(_def)
        varz = {}
        kode = parser.parse_func(_def, _globals, {"self": sigs}, origcode, varz)
        gascost = compile_lll.gas_estimate(kode) + initial_gas
        o[name] = gascost + memsize_to_gas(varz.get("_next_mem", parser.RESERVED_MEMORY)) + function_gas * i
    return o

# Dummy object, as some tools expect this interface
class Compiler():

    def compile(self, code, *args, **kwargs):
        return compile(code, *args, **kwargs)

    def mk_full_signature(self, code, *args, **kwargs):
        return mk_full_signature(code, *args, **kwargs)

    def gas_estimate(self, code, *args, **kwargs):
        return gas_estimate(code, *args, **kwargs)
