from vyper.compiler.phases import CompilerData

from vyper.interpret.context import InterpreterContext
from vyper.interpret.stmt import Stmt

class VyperFunction:
    def __init__(self, fn_ast, global_ctx):
        self.fn_ast = fn_ast
        self.ctx = InterpreterContext(global_ctx)

    def __call__(self, *args, **kwargs):
        #self.ctx.set_args(self.*args)
        #self.ctx.set_kwargs(**kwargs)

        for stmt in self.fn_ast.body:
            t = Stmt(stmt, self.ctx).interpret()
            if t is not None:
                return t

class VyperContract:
    def __init__(self, global_ctx):
        self.global_ctx = global_ctx

        functions = {fn.name: fn for fn in global_ctx._function_defs}

        for fn in global_ctx._function_defs:
            setattr(self, fn.name, VyperFunction(fn, global_ctx))

def load(filename: str) -> VyperContract:
    with open(filename) as f:
        data = CompilerData(f.read())

    return VyperContract(data.global_ctx)
