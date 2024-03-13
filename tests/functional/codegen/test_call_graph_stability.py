import random
import string

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

import vyper.ast as vy_ast
from vyper.ast.identifiers import RESERVED_KEYWORDS
from vyper.compiler.phases import CompilerData


def _valid_identifier(attr):
    return attr not in RESERVED_KEYWORDS


# random names for functions
@settings(max_examples=20)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["@pure", "@view", "@nonpayable", "@payable"]),
            st.text(alphabet=string.ascii_lowercase, min_size=1).filter(_valid_identifier),
        ),
        unique_by=lambda x: x[1],  # unique on function name
        min_size=1,
        max_size=10,
    )
)
@pytest.mark.fuzzing
def test_call_graph_stability_fuzz(funcs):
    def generate_func_def(mutability, func_name, i):
        return f"""
@internal
{mutability}
def {func_name}() -> uint256:
    return {i}
        """

    func_defs = "\n".join(generate_func_def(m, s, i) for i, (m, s) in enumerate(funcs))

    for _ in range(10):
        func_names = [f for (_, f) in funcs]
        random.shuffle(func_names)

        self_calls = "\n".join(f"  self.{f}()" for f in func_names)
        code = f"""
{func_defs}

@external
def foo():
{self_calls}
        """
        t = CompilerData(code)

        # check the .called_functions data structure on foo() directly
        foo = t.annotated_vyper_module.get_children(vy_ast.FunctionDef, filters={"name": "foo"})[0]
        foo_t = foo._metadata["func_type"]
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

        expected = []
        for f in foo_t.called_functions:
            expected.append(f._ir_info.internal_function_label(is_ctor_context=False))

        assert ir_funcs == expected
