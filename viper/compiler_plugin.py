from . import parser
from . import compile_lll

def memsize_to_gas(memsize):
    return (memsize // 32) * 3 + (memsize // 32) ** 2 // 512

initial_gas = compile_lll.gas_estimate(parser.mk_initial())

class Compiler():
    def compile(self, code, *args, **kwargs):
        lll = parser.parse_tree_to_lll(parser.parse(code))
        return compile_lll.assembly_to_evm(compile_lll.compile_to_assembly(lll))

    def mk_full_signature(self, code, *args, **kwargs):
        o = parser.mk_full_signature(parser.parse(code))
        return o

    def gas_estimate(self, code, *args, **kwargs):
        code = parser.parse(code)
        _defs, _globals = parser.get_defs_and_globals(code)
        o = {}
        for _def in _defs:
            name, args, output_type, const, sig, method_id = parser.get_func_details(_def)
            varz = {}
            kode = parser.parse_func(_def, _globals, varz)
            gascost = compile_lll.gas_estimate(kode) + initial_gas
            o[name] = gascost + memsize_to_gas(varz.get("_next_mem", parser.RESERVED_MEMORY)) + 68 * (4 + 32 * len(args))
        return o
