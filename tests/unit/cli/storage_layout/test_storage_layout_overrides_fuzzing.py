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
# TODO move this to a better test location

import copy
import math
import random
from dataclasses import dataclass

import pytest
from hypothesis import Phase, given, settings
from hypothesis import strategies as st

# TODO use proper generator for storage types
from tests.functional.builtins.codegen.test_abi_decode_fuzz import vyper_type
from vyper.compiler import compile_code
from vyper.semantics.types import HashMapT

ENABLE_TRANSIENT = False


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
    should_raise: bool
    final_layout: dict


@dataclass
class MutationResult:
    success: bool
    layout: dict


VAR_NAME_COUNTER = 0


def get_var_name():
    global VAR_NAME_COUNTER
    varname = "var" + str(VAR_NAME_COUNTER)
    VAR_NAME_COUNTER += 1
    return varname


@st.composite
def generate_contract_parts(draw):
    num_vars = draw(st.integers(1, 50))
    type_definitions = []
    declarations = []

    for _ in range(num_vars):
        name = get_var_name()

        # TODO verify that we're covering all types
        # think we're missing (atleast) Flags, Interfaces, Decimals
        num = draw(st.integers(1, 4))
        source_fragments, typ = draw(vyper_type(num))
        type_definitions.extend(source_fragments)  # Struct definitions
        probability = draw(st.floats(0, 1))
        do_transient_decl = probability <= 0.1
        if do_transient_decl and not isinstance(typ, HashMapT):
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


@st.composite
def _select_section(draw, layout):
    if not ENABLE_TRANSIENT:
        return layout["storage_layout"]
    section = draw(st.sampled_from(["storage_layout", "transient_storage_layout"]))
    if section not in layout or not layout[section]:
        section = "transient_storage_layout" if section == "storage_layout" else "storage_layout"
    return layout[section]


@st.composite
def drop_random_item(draw, layout) -> MutationResult:
    result = layout
    section = draw(_select_section(layout))

    if len(section) == 0:
        return MutationResult(False, result)

    keys = st.sampled_from(list(section.keys()))
    item_name = draw(keys)
    del section[item_name]

    return MutationResult(success=True, layout=result)


@st.composite
def mutate_slot_address(draw, layout) -> MutationResult:
    result = layout
    section = draw(_select_section(layout))

    if len(section) < 2:
        return MutationResult(False, result)

    items = list(section.keys())
    item_name = draw(st.sampled_from(items[:-1]))
    last_slot = section[items[-1]]["slot"]
    assert last_slot > 0
    strategy = st.integers(0, last_slot)
    new_slot = draw(strategy)
    while section[item_name]["slot"] == new_slot:
        new_slot = draw(strategy)
    section[item_name]["slot"] = new_slot

    return MutationResult(success=True, layout=result)


@st.composite
def mutate_slot_size(draw, layout) -> MutationResult:
    result = layout
    section = draw(_select_section(layout))

    if len(section) < 2:
        return MutationResult(False, result)

    items = list(section.keys())
    item_name = draw(st.sampled_from(items[:-1]))
    last_slot = section[items[-1]]["slot"]
    strategy = st.integers(-last_slot, last_slot)
    delta = draw(strategy)
    while delta == 0:
        delta = draw(strategy)
    section[item_name]["n_slots"] = section[item_name]["n_slots"] + delta

    return MutationResult(success=True, layout=result)


@st.composite
def mutate_layout(draw, layout):
    mutation_strategies = [drop_random_item, mutate_slot_address, mutate_slot_size]

    mutation = draw(st.sampled_from(mutation_strategies))

    result = layout

    mutation_result = draw(mutation(result))
    should_raise = mutation_result.success
    result = mutation_result.layout

    return should_raise, result


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
    should_raise, mutated_layout = draw(mutate_layout(copy.deepcopy(perm.layout)))

    return ContractMutation(
        permutation=perm, should_raise=should_raise, final_layout=mutated_layout
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
