import pytest

from vyper.exceptions import (
    ArrayIndexException,
    InvalidType,
    StructureException,
    UndeclaredDefinition,
)
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import PRIMITIVE_TYPES, HashMapT, SArrayT
from vyper.semantics.types.utils import type_from_annotation

BASE_TYPES = ["int128", "uint256", "bool", "address", "bytes32"]
BYTESTRING_TYPES = ["String", "Bytes"]


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("location", iter(DataLocation))
def test_base_types(build_node, type_str, location):
    node = build_node(type_str)
    base_t = PRIMITIVE_TYPES[type_str]

    ann_t = type_from_annotation(node)

    assert base_t == ann_t


@pytest.mark.parametrize("type_str", BYTESTRING_TYPES)
@pytest.mark.parametrize("location", iter(DataLocation))
def test_array_value_types(build_node, type_str, location):
    node = build_node(f"{type_str}[1]")
    base_t = PRIMITIVE_TYPES[type_str](1)

    ann_t = type_from_annotation(node)

    assert base_t == ann_t


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("location", iter(DataLocation))
def test_base_types_as_arrays(build_node, type_str, location):
    node = build_node(f"{type_str}[3]")
    base_t = PRIMITIVE_TYPES[type_str]

    ann_t = type_from_annotation(node)

    assert ann_t == SArrayT(base_t, 3)


@pytest.mark.parametrize("type_str", BYTESTRING_TYPES)
@pytest.mark.parametrize("location", iter(DataLocation))
def test_array_value_types_as_arrays(build_node, type_str, location):
    node = build_node(f"{type_str}[1][1]")

    with pytest.raises(StructureException):
        type_from_annotation(node)


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("location", iter(DataLocation))
def test_base_types_as_multidimensional_arrays(build_node, namespace, type_str, location):
    node = build_node(f"{type_str}[3][5]")
    base_t = PRIMITIVE_TYPES[type_str]

    ann_t = type_from_annotation(node)

    assert ann_t == SArrayT(SArrayT(base_t, 3), 5)


@pytest.mark.parametrize("type_str", ["int128", "String"])
@pytest.mark.parametrize("idx", ["0", "-1", "0x00", "'1'", "foo", "[1]", "(1,)"])
@pytest.mark.parametrize("location", iter(DataLocation))
def test_invalid_index(build_node, idx, type_str, location):
    node = build_node(f"{type_str}[{idx}]")
    with pytest.raises(
        (ArrayIndexException, InvalidType, StructureException, UndeclaredDefinition)
    ):
        type_from_annotation(node)


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("type_str2", BASE_TYPES)
def test_mapping(build_node, type_str, type_str2):
    node = build_node(f"HashMap[{type_str}, {type_str2}]")
    types = PRIMITIVE_TYPES

    ann_t = type_from_annotation(node, DataLocation.STORAGE)

    k_t = types[type_str]
    v_t = types[type_str2]

    assert ann_t == HashMapT(k_t, v_t)


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("type_str2", BASE_TYPES)
def test_multidimensional_mapping(build_node, type_str, type_str2):
    node = build_node(f"HashMap[{type_str}, HashMap[{type_str}, {type_str2}]]")
    types = PRIMITIVE_TYPES

    ann_t = type_from_annotation(node, DataLocation.STORAGE)

    k_t = types[type_str]
    v_t = types[type_str2]

    assert ann_t == HashMapT(k_t, HashMapT(k_t, v_t))
