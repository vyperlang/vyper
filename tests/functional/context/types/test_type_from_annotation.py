import pytest

from vyper.context.types import get_pure_types
from vyper.context.types.indexable.mapping import MappingDefinition
from vyper.context.types.indexable.sequence import ArrayDefinition
from vyper.context.types.utils import get_type_from_annotation
from vyper.exceptions import (
    ArrayIndexException,
    InvalidType,
    StructureException,
)

BASE_TYPES = ["int128", "uint256", "bool", "address", "bytes32"]
ARRAY_VALUE_TYPES = ["string", "bytes"]


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types(build_node, namespace, type_str):
    node = build_node(type_str)
    pure_type = get_pure_types()[type_str]

    with namespace.enter_builtin_scope():
        type_definition = get_type_from_annotation(node)

    assert isinstance(type_definition, pure_type._type)


@pytest.mark.parametrize("type_str", ARRAY_VALUE_TYPES)
def test_array_value_types(build_node, namespace, type_str):
    node = build_node(f"{type_str}[1]")
    pure_type = get_pure_types()[type_str]

    with namespace.enter_builtin_scope():
        type_definition = get_type_from_annotation(node)

    assert isinstance(type_definition, pure_type._type)


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types_as_arrays(build_node, namespace, type_str):
    node = build_node(f"{type_str}[3]")
    pure_type = get_pure_types()[type_str]

    with namespace.enter_builtin_scope():
        type_definition = get_type_from_annotation(node)

    assert isinstance(type_definition, ArrayDefinition)
    assert type_definition.length == 3
    assert isinstance(type_definition.value_type, pure_type._type)


@pytest.mark.parametrize("type_str", ARRAY_VALUE_TYPES)
def test_array_value_types_as_arrays(build_node, namespace, type_str):
    node = build_node(f"{type_str}[1][1]")

    with namespace.enter_builtin_scope():
        with pytest.raises(StructureException):
            get_type_from_annotation(node)


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types_as_multidimensional_arrays(build_node, namespace, type_str):
    node = build_node(f"{type_str}[3][5]")
    pure_type = get_pure_types()[type_str]

    with namespace.enter_builtin_scope():
        type_definition = get_type_from_annotation(node)

    assert isinstance(type_definition, ArrayDefinition)
    assert type_definition.length == 5
    assert isinstance(type_definition.value_type, ArrayDefinition)
    assert type_definition.value_type.length == 3
    assert isinstance(type_definition.value_type.value_type, pure_type._type)


@pytest.mark.parametrize("type_str", ["int128", "string"])
@pytest.mark.parametrize("idx", ["0", "-1", "0x00", "'1'", "foo", "[1]", "(1,)"])
def test_invalid_index(build_node, namespace, idx, type_str):
    node = build_node(f"{type_str}[{idx}]")
    with namespace.enter_builtin_scope():
        with pytest.raises((ArrayIndexException, InvalidType)):
            get_type_from_annotation(node)


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("type_str2", BASE_TYPES)
def test_mapping(build_node, namespace, type_str, type_str2):
    node = build_node(f"map({type_str}, {type_str2})")
    pure_types = get_pure_types()

    with namespace.enter_builtin_scope():
        type_definition = get_type_from_annotation(node)

    assert isinstance(type_definition, MappingDefinition)
    assert isinstance(type_definition.key_type, pure_types[type_str]._type)
    assert isinstance(type_definition.value_type, pure_types[type_str2]._type)


@pytest.mark.parametrize("type_str", BASE_TYPES)
@pytest.mark.parametrize("type_str2", BASE_TYPES)
def test_multidimensional_mapping(build_node, namespace, type_str, type_str2):
    node = build_node(f"map({type_str}, map({type_str}, {type_str2}))")
    pure_types = get_pure_types()

    with namespace.enter_builtin_scope():
        type_definition = get_type_from_annotation(node)

    assert isinstance(type_definition, MappingDefinition)
    assert isinstance(type_definition.key_type, pure_types[type_str]._type)
    assert isinstance(type_definition.value_type, MappingDefinition)
    assert isinstance(type_definition.value_type.key_type, pure_types[type_str]._type)
    assert isinstance(type_definition.value_type.value_type, pure_types[type_str2]._type)
