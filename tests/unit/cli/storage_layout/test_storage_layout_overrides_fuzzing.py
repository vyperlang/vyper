"""
1. generate random storage and transient variable declarations
2. generate random permutations of the declarations
3. stochastically add errors into the permutations
    - drop variable
    - modify address slot
    - modify size of variable
4. check that the original contract from 1) compiles with the layouts of the permutations
5. further, if a layout has an invalid mutation, the compilation with this layout must fail
"""
# TODO move this to a proper test directory

import copy
import math
import random
import string
from dataclasses import dataclass

import pytest
from hypothesis import Phase, given, settings
from hypothesis import strategies as st

# TODO use proper generator for storage types
from tests.functional.builtins.codegen.test_abi_decode_fuzz import vyper_type
from vyper.compiler import compile_code
from vyper.semantics.types import HashMapT


@dataclass
class ContractParts:
    types: list[str]
    declarations: list[str]
    source: str


@dataclass
class ContractPermutation:
    contract: ContractParts
    permutation: tuple[str, ...]
    permuted_source: str
    layout: dict


@dataclass
class ContractMutation:
    permutation: ContractPermutation
    mutations: list[str]
    should_raise: bool
    final_layout: dict


@dataclass
class MutationResult:
    success: bool
    layout: dict
    description: str


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


# sanity check a storage layout
# check that variables don't overlap and that each var starts
# where the previous one ends (doesn't account for hash ptrs)
def validate_storage_layout(layout_dict):
    for section in ["storage_layout", "transient_storage_layout"]:
        if section not in layout_dict:
            continue

        variables = [info for _, info in layout_dict[section].items()]
        # variables.sort(key=lambda x: x["slot"])

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


def drop_random_item(layout) -> MutationResult:
    result = layout
    section = _select_section(layout)

    item_name = random.choice(list(result[section].keys()))
    del result[section][item_name]

    return MutationResult(
        success=True, layout=result, description=f"Dropped item '{item_name}' from {section}"
    )


def modify_slot_addresses(layout) -> MutationResult:
    result = layout
    section = _select_section(layout)

    items = list(result[section].keys())
    if len(items) < 2:
        return MutationResult(False, result, "Not enough items to modify slots")

    # NOTE: dictionaries retain the insertion order and the variables are inserted
    # in the order they are declared, and thus modifying the slot of any but the last
    # item s.t. the slot will remain in the original slot range is a valid mutation
    # that should cause exception in the allocator when this mutation is used.
    # Further, if the allocation strategy should change the these mutations should raise
    # instead of silently passing, and thus the assumed behavior should be safe
    item_name = random.choice(items[:-1])
    last_slot = result[section][items[-1]]["slot"]
    # NOTE: should we test for negative values?
    new_slot = st.integers(min_value=0, max_value=last_slot)
    result[section][item_name]["slot"] = new_slot

    return MutationResult(
        success=True, layout=result, description=f"Changed slot of '{item_name}' to {new_slot}"
    )


def modify_slot_sizes(layout) -> MutationResult:
    result = layout
    section = _select_section(layout)

    items = list(result[section].keys())
    item_name = random.choice(items[:-1])
    last_slot = result[section][items[-1]]["slot"]
    # this also creates layouts, where `n_slots` is negative
    delta = st.integers(min_value=-last_slot, max_value=last_slot)
    while delta == 0:
        delta = st.integers(min_value=-last_slot, max_value=last_slot)
    result[section][item_name]["n_slots"] = result[section][item_name]["n_slots"] + delta

    return MutationResult(
        success=True, layout=result, description=f"Modified n_slots of '{item_name}' by {delta}"
    )


def mutate_layout(layout) -> tuple[bool, dict, list[str]]:
    mutation_funcs = [drop_random_item, modify_slot_addresses, modify_slot_sizes]

    n_mutations = random.randint(1, len(mutation_funcs))
    selected_mutations = random.sample(mutation_funcs, n_mutations)

    result = layout
    should_raise = False
    mutation_history = []

    for mutation_func in selected_mutations:
        mutation_result = mutation_func(result)
        should_raise |= mutation_result.success
        result = mutation_result.layout
        mutation_history.append(mutation_result.description)

    return should_raise, result, mutation_history


@st.composite
def contract_strategy(draw) -> ContractParts:
    types, declarations = draw(generate_contract_parts())
    source = "\n".join(types + declarations)
    return ContractParts(types, declarations, source)


@st.composite
def permutation_strategy(draw) -> ContractPermutation:
    contract = draw(contract_strategy())
    perm = list(contract.declarations)
    random.shuffle(perm)
    perm = tuple(perm)

    permuted_source = "\n".join(contract.types + list(perm))
    out = compile_code(permuted_source, output_formats=["layout"])
    validate_storage_layout(out["layout"])

    return ContractPermutation(
        contract=contract, permutation=perm, permuted_source=permuted_source, layout=out["layout"]
    )


@st.composite
def mutation_strategy(draw) -> ContractMutation:
    perm = draw(permutation_strategy())
    # deepcopy to avoid modifying the original layout
    # which is used later
    should_raise, mutated_layout, mutation_history = mutate_layout(copy.deepcopy(perm.layout))

    return ContractMutation(
        permutation=perm,
        mutations=mutation_history,
        should_raise=should_raise,
        final_layout=mutated_layout,
    )


@pytest.mark.fuzzing
@given(mutation_strategy())
@settings(phases=[Phase.generate], max_examples=1000)  # , verbosity=Verbosity.verbose)
def test_override_fuzzing(mutation: ContractMutation):
    # test that original contract compiles
    # with permutation's layout
    out2 = compile_code(
        mutation.permutation.contract.source,
        storage_layout_override=mutation.permutation.layout["storage_layout"],
        output_formats=["layout"],
    )

    # test that the permutation's layout is the same as the final layout
    assert mutation.permutation.layout["storage_layout"] == out2["layout"]["storage_layout"]

    if mutation.should_raise:
        # TODO can we do more precise error checking?
        with pytest.raises(Exception):
            compile_code(
                mutation.permutation.contract.source,
                storage_layout_override=mutation.final_layout["storage_layout"],
                output_formats=["layout"],
            )
