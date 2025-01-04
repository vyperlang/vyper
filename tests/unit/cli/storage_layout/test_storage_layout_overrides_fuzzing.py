import random
import string
from hypothesis import strategies as st
from hypothesis import given, settings, Phase
import pytest
import math

# TODO use proper generator for storage types
from tests.functional.builtins.codegen.test_abi_decode_fuzz import vyper_type

from vyper.compiler import compile_code

def generate_var_name():
    length = random.randint(1, 30)
    first_char = random.choice(string.ascii_letters + '_')
    rest = ''.join(random.choice(string.ascii_letters + string.digits + '_')
                   for _ in range(length - 1))
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

        # TODO fix struct namespace collision
        source_fragments, typ = draw(vyper_type())
        type_definitions.extend(source_fragments)  # Struct definitions
        declarations.append(f"{name}: {str(typ)}")

    return type_definitions, declarations

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
    original_source = '\n'.join(types + declarations)
    perms = generate_permutations(declarations)

    for perm in perms:
        perm_source = '\n'.join(types + list(perm))
        out = compile_code(perm_source, output_formats=["layout"])
        out2 = compile_code(original_source, storage_layout_override=out["layout"]["storage_layout"], output_formats=["layout"])
        assert out["layout"]["storage_layout"] == out2["layout"]["storage_layout"]
