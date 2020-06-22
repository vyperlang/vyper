import pytest

from vyper.context.types import get_pure_types
from vyper.context.types.indexable.sequence import ArrayDefinition
from vyper.context.types.utils import get_type_from_abi
from vyper.exceptions import UnknownType

BASE_TYPES = ["int128", "uint256", "bool", "address", "bytes32"]


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types(namespace, type_str):
    pure_type = get_pure_types()[type_str]

    with namespace.enter_builtin_scope():
        type_definition = get_type_from_abi({"type": type_str})

    assert isinstance(type_definition, pure_type._type)


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types_as_arrays(namespace, type_str):
    pure_type = get_pure_types()[type_str]

    with namespace.enter_builtin_scope():
        type_definition = get_type_from_abi({"type": f"{type_str}[3]"})

    assert isinstance(type_definition, ArrayDefinition)
    assert type_definition.length == 3
    assert isinstance(type_definition.value_type, pure_type._type)


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types_as_multidimensional_arrays(namespace, type_str):
    pure_type = get_pure_types()[type_str]

    with namespace.enter_builtin_scope():
        type_definition = get_type_from_abi({"type": f"{type_str}[3][5]"})

    assert isinstance(type_definition, ArrayDefinition)
    assert type_definition.length == 5
    assert isinstance(type_definition.value_type, ArrayDefinition)
    assert type_definition.value_type.length == 3
    assert isinstance(type_definition.value_type.value_type, pure_type._type)


@pytest.mark.parametrize("idx", ["0", "-1", "0x00", "'1'", "foo", "[1]", "(1,)"])
def test_invalid_index(namespace, idx):
    with namespace.enter_builtin_scope():
        with pytest.raises(UnknownType):
            get_type_from_abi({"type": f"int128[{idx}]"})
