import pytest

from vyper.semantics.types.utils import type_from_annotation

BASE_TYPES = ["int128", "uint256", "bool", "address", "bytes32"]
BYTESTRING_TYPES = ["String", "Bytes"]


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types(build_node, type_str):
    node = build_node(type_str)
    type_definition = type_from_annotation(node)

    assert type_definition.size_in_bytes == 32


@pytest.mark.parametrize("type_str", BYTESTRING_TYPES)
@pytest.mark.parametrize("length,size", [(1, 64), (32, 64), (33, 96), (86, 128)])
def test_array_value_types(build_node, type_str, length, size):
    node = build_node(f"{type_str}[{length}]")
    type_definition = type_from_annotation(node)

    assert type_definition.size_in_bytes == size


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("length", range(1, 4))
def test_dynamic_array_lengths(build_node, type_str, length):
    node = build_node(f"DynArray[{type_str}, {length}]")
    type_definition = type_from_annotation(node)

    assert type_definition.size_in_bytes == 32 + length * 32


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("length", range(1, 4))
def test_base_types_as_arrays(build_node, type_str, length):
    node = build_node(f"{type_str}[{length}]")
    type_definition = type_from_annotation(node)

    assert type_definition.size_in_bytes == length * 32


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("first", range(1, 4))
@pytest.mark.parametrize("second", range(1, 4))
def test_base_types_as_multidimensional_arrays(build_node, type_str, first, second):
    node = build_node(f"{type_str}[{first}][{second}]")

    type_definition = type_from_annotation(node)

    assert type_definition.size_in_bytes == first * second * 32
