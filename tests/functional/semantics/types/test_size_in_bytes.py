import pytest

from vyper.semantics.types.bases import DataLocation
from vyper.semantics.types.utils import get_type_from_annotation

BASE_TYPES = ["int128", "uint256", "bool", "address", "bytes32"]
ARRAY_VALUE_TYPES = ["String", "Bytes"]
LOCATIONS = [DataLocation.STORAGE, DataLocation.MEMORY, DataLocation.STORAGE]


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("location", LOCATIONS)
def test_base_types(build_node, type_str, location):
    node = build_node(type_str)
    type_definition = get_type_from_annotation(node, location)

    assert type_definition.size_in_bytes == 32


@pytest.mark.parametrize("type_str", ARRAY_VALUE_TYPES)
@pytest.mark.parametrize("location", LOCATIONS)
@pytest.mark.parametrize("length,size", [(1, 64), (32, 64), (33, 96), (86, 128)])
def test_array_value_types(build_node, type_str, location, length, size):
    node = build_node(f"{type_str}[{length}]")
    type_definition = get_type_from_annotation(node, location)

    assert type_definition.size_in_bytes == size


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("location", LOCATIONS)
@pytest.mark.parametrize("length", range(1, 4))
def test_dynamic_array_lengths(build_node, type_str, location, length):
    node = build_node(f"DynArray[{type_str}, {length}]")
    type_definition = get_type_from_annotation(node, location)

    assert type_definition.size_in_bytes == 32 + length * 32


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("location", LOCATIONS)
@pytest.mark.parametrize("length", range(1, 4))
def test_base_types_as_arrays(build_node, type_str, location, length):
    node = build_node(f"{type_str}[{length}]")
    type_definition = get_type_from_annotation(node, location)

    assert type_definition.size_in_bytes == length * 32


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("location", LOCATIONS)
@pytest.mark.parametrize("first", range(1, 4))
@pytest.mark.parametrize("second", range(1, 4))
def test_base_types_as_multidimensional_arrays(build_node, type_str, location, first, second):
    node = build_node(f"{type_str}[{first}][{second}]")

    type_definition = get_type_from_annotation(node, location)

    assert type_definition.size_in_bytes == first * second * 32
