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
    num_vars = random.randint(1, 50)
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

        variables = [info for _, info in layout_dict[section].items()]
        variables.sort(key=lambda x: x["slot"])

        counter = variables[0]["slot"]
        for info in variables:
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


def _select_section(layout):
    section = random.choice(["storage_layout", "transient_storage_layout"])
    if section not in layout or not layout[section]:
        section = "transient_storage_layout" if section == "storage_layout" else "storage_layout"
    return section


def drop_random_item(layout):
    result = layout
    section = _select_section(layout)

    item_name = random.choice(list(result[section].keys()))
    del result[section][item_name]

    return True, result


def _modify_field(layout, field_name):
    result = layout
    section = _select_section(layout)

    items = list(result[section].keys())

    if len(items) < 2:
        return False, result

    item_name = random.choice(items[:-1])

    delta = random.choice([-1, 1])
    if field_name == "n_slots":
        result[section][item_name][field_name] = max(
            1, result[section][item_name][field_name] + delta
        )
    else:
        result[section][item_name][field_name] += delta

    return True, result


def modify_slot_addresses(layout):
    return _modify_field(layout, "slot")


def modify_slot_sizes(layout):
    return _modify_field(layout, "n_slots")


def mutate_layout(layout):
    mutation_funcs = [
        # TODO what about duplicate?
        drop_random_item,
        modify_slot_addresses,
        modify_slot_sizes,
    ]

    n_mutations = random.randint(1, len(mutation_funcs))
    selected_mutations = random.sample(mutation_funcs, n_mutations)

    result = layout

    should_raise = False
    for mutation_func in selected_mutations:
        mutated, result = mutation_func(result)
        should_raise |= not mutated

    return should_raise, result


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

        should_raise, mutated_layout = mutate_layout(out["layout"])
        if not should_raise:
            continue
        # TODO can we be more specific
        with pytest.raises(Exception):
            compile_code(
                original_source,
                storage_layout_override=mutated_layout["storage_layout"],
                output_formats=["layout"],
            )
