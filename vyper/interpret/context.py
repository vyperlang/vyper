
class InterpreterContext:
    def __init__(self, global_ctx):
        self.global_ctx = global_ctx
        self.local_variables = {}
        self.storage_variables = {}
        self.immutables = {}

    def set_args(*args):
        print(*args)

    def set_var(self, varname, val):
        self.local_variables[varname] = val

    def get_var(self, varname):
        if varname in self.local_variables:
            return self.local_variables[varname]
