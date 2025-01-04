import math
import random
import string

import pytest
from hypothesis import Phase, given, settings
from hypothesis import strategies as st

# TODO use proper generator for storage types
from tests.functional.builtins.codegen.test_abi_decode_fuzz import vyper_type
from vyper.compiler import compile_code
from vyper.semantics.types import HashMapT


def generate_var_name():
    length = random.randint(1, 30)
    first_char = random.choice(string.ascii_letters + "_")
    rest = "".join(
        random.choice(string.ascii_letters + string.digits + "_") for _ in range(length - 1)
    )
    return first_char + rest


@st.composite
def generate_contract_parts(draw):
    num_vars = random.randint(1, 100)
    type_definitions = []
    declarations = []
    used_names = set()

    for _ in range(num_vars):
        while True:
            name = generate_var_name()
            if name not in used_names:
                used_names.add(name)
                break

        # TODO verify that we're covering all types
        # think we're missing (atleast) Flags, Interfaces, Decimals
        source_fragments, typ = draw(vyper_type(random.randint(1, 4)))
        type_definitions.extend(source_fragments)  # Struct definitions
        transient_decl = random.random() < 0.1
        if transient_decl and not isinstance(typ, HashMapT):
            declarations.append(f"{name}: transient({str(typ)})")
        else:
            declarations.append(f"{name}: {str(typ)}")
        # TODO add a function with @nonreentrant and compile w/o cancun

    return type_definitions, declarations


def validate_storage_layout(layout_dict):
    for section in ["storage_layout", "transient_storage_layout"]:
        if section not in layout_dict:
            continue

        variables = [(name, info) for name, info in layout_dict[section].items()]
        variables.sort(key=lambda x: x[1]["slot"])

        counter = variables[0][1]["slot"]
        for _, info in variables:
            if info["slot"] != counter:
                raise ValueError("Invalid layout")
            counter += info["n_slots"]


def generate_permutations(declarations: list, num_permutations: int = 50):
    num_permutations = min(num_permutations, math.factorial(len(declarations)))
    result = []
    for _ in range(num_permutations):
        perm = list(declarations)
        random.shuffle(perm)
        result.append(tuple(perm))
    return result


@pytest.mark.fuzzing
@given(generate_contract_parts())
@settings(phases=[Phase.generate], max_examples=50)
def test_override_fuzzing(contract_parts):
    types, declarations = contract_parts
    original_source = "\n".join(types + declarations)
    perms = generate_permutations(declarations)

    for perm in perms:
        perm_source = "\n".join(types + list(perm))
        out = compile_code(perm_source, output_formats=["layout"])
        validate_storage_layout(out["layout"])
        out2 = compile_code(
            original_source,
            storage_layout_override=out["layout"]["storage_layout"],
            output_formats=["layout"],
        )
        assert out["layout"]["storage_layout"] == out2["layout"]["storage_layout"]
