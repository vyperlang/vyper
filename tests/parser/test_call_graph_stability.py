import random
import string

import pytest
from hypothesis import given, settings
from hypothesis.strategies import lists, text

import vyper.ast as vy_ast
from vyper.compiler.phases import CompilerData


# random names for functions
@settings(max_examples=20, deadline=1000)
@given(
    lists(text(alphabet=string.ascii_lowercase, min_size=1), unique=True, min_size=1, max_size=10)
)
@pytest.mark.fuzzing
def test_call_graph_stability_fuzz(func_names):
    def generate_func_def(func_name, i):
        return f"""
@internal
def {func_name}() -> uint256:
    return {i}
        """

    func_defs = "\n".join(generate_func_def(s, i) for i, s in enumerate(func_names))

    for _ in range(10):
        fs = func_names.copy()
        random.shuffle(fs)

        self_calls = "\n".join(f"  self.{f}()" for f in func_names)
        code = f"""
{func_defs}

@external
def foo():
{self_calls}
        """
        t = CompilerData(code)

        # check the .called_functions data structure on foo() directly
        foo = t.vyper_module_folded.get_children(vy_ast.FunctionDef, filters={"name": "foo"})[0]
        foo_t = foo._metadata["type"]
        assert [f.name for f in foo_t.called_functions] == func_names

        # now for sanity, ensure the order that the function definitions appear
        # in the IR is the same as the order of the calls
        sigs = t.function_signatures
        del sigs["foo"]
        ir = t.ir_runtime
        ir_funcs = []
        # search for function labels
        for d in ir.args:  # currently: (seq ... (seq (label foo ...)) ...)
            if d.value == "seq" and d.args[0].value == "label":
                r = d.args[0].args[0].value
                if isinstance(r, str) and r.startswith("internal"):
                    ir_funcs.append(r)
        assert ir_funcs == [f.internal_function_label for f in sigs.values()]
