import pytest

from vyper.exceptions import (
    ArrayIndexException,
    InvalidType,
    StructureException,
    UndeclaredDefinition,
)
from vyper.semantics.types import get_primitive_types
from vyper.semantics.types.bases import DataLocation
from vyper.semantics.types.indexable.mapping import MappingDefinition
from vyper.semantics.types.indexable.sequence import ArrayDefinition
from vyper.semantics.types.utils import get_type_from_annotation

BASE_TYPES = ["int128", "uint256", "bool", "address", "bytes32"]
ARRAY_VALUE_TYPES = ["String", "Bytes"]


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types(build_node, type_str):
    node = build_node(type_str)
    primitive = get_primitive_types()[type_str]

    type_definition = get_type_from_annotation(node, DataLocation.STORAGE)

    assert isinstance(type_definition, primitive._type)


@pytest.mark.parametrize("type_str", ARRAY_VALUE_TYPES)
def test_array_value_types(build_node, type_str):
    node = build_node(f"{type_str}[1]")
    primitive = get_primitive_types()[type_str]

    type_definition = get_type_from_annotation(node, DataLocation.STORAGE)

    assert isinstance(type_definition, primitive._type)


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types_as_arrays(build_node, type_str):
    node = build_node(f"{type_str}[3]")
    primitive = get_primitive_types()[type_str]

    type_definition = get_type_from_annotation(node, DataLocation.STORAGE)

    assert isinstance(type_definition, ArrayDefinition)
    assert type_definition.length == 3
    assert isinstance(type_definition.value_type, primitive._type)


@pytest.mark.parametrize("type_str", ARRAY_VALUE_TYPES)
def test_array_value_types_as_arrays(build_node, type_str):
    node = build_node(f"{type_str}[1][1]")

    with pytest.raises(StructureException):
        get_type_from_annotation(node, DataLocation.STORAGE)


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types_as_multidimensional_arrays(build_node, namespace, type_str):
    node = build_node(f"{type_str}[3][5]")
    primitive = get_primitive_types()[type_str]

    type_definition = get_type_from_annotation(node, DataLocation.STORAGE)

    assert isinstance(type_definition, ArrayDefinition)
    assert type_definition.length == 5
    assert isinstance(type_definition.value_type, ArrayDefinition)
    assert type_definition.value_type.length == 3
    assert isinstance(type_definition.value_type.value_type, primitive._type)


@pytest.mark.parametrize("type_str", ["int128", "String"])
@pytest.mark.parametrize("idx", ["0", "-1", "0x00", "'1'", "foo", "[1]", "(1,)"])
def test_invalid_index(build_node, idx, type_str):
    node = build_node(f"{type_str}[{idx}]")
    with pytest.raises(
        (ArrayIndexException, InvalidType, StructureException, UndeclaredDefinition)
    ):
        get_type_from_annotation(node, DataLocation.STORAGE)


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("type_str2", BASE_TYPES)
def test_mapping(build_node, type_str, type_str2):
    node = build_node(f"HashMap[{type_str}, {type_str2}]")
    primitives = get_primitive_types()

    type_definition = get_type_from_annotation(node, DataLocation.STORAGE)

    assert isinstance(type_definition, MappingDefinition)
    assert isinstance(type_definition.key_type, primitives[type_str]._type)
    assert isinstance(type_definition.value_type, primitives[type_str2]._type)


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("type_str2", BASE_TYPES)
def test_multidimensional_mapping(build_node, type_str, type_str2):
    node = build_node(f"HashMap[{type_str}, HashMap[{type_str}, {type_str2}]]")
    primitives = get_primitive_types()

    type_definition = get_type_from_annotation(node, DataLocation.STORAGE)

    assert isinstance(type_definition, MappingDefinition)
    assert isinstance(type_definition.key_type, primitives[type_str]._type)
    assert isinstance(type_definition.value_type, MappingDefinition)
    assert isinstance(type_definition.value_type.key_type, primitives[type_str]._type)
    assert isinstance(type_definition.value_type.value_type, primitives[type_str2]._type)
